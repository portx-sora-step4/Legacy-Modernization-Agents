using Microsoft.Extensions.AI;
using Microsoft.Extensions.Logging;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;

using AIChatMessage = Microsoft.Extensions.AI.ChatMessage;

namespace CobolToQuarkusMigration.Agents.Infrastructure;

/// <summary>
/// Configuration for the local Python Codex SDK sidecar.
/// </summary>
public sealed record CodexSdkChatClientOptions
{
    public string PythonExecutable { get; init; } = OperatingSystem.IsWindows() ? "python" : "python3";
    public string SidecarScriptPath { get; init; } = Path.Combine("Scripts", "codex_sdk_sidecar.py");
    public string WorkingDirectory { get; init; } = Directory.GetCurrentDirectory();
    public string Sandbox { get; init; } = "read-only";
    public string? CodexExecutable { get; init; }
    public TimeSpan RequestTimeout { get; init; } = TimeSpan.FromMinutes(5);
    public int MaxStandardOutputCharacters { get; init; } = 16 * 1024 * 1024;
    public int MaxStandardErrorCharacters { get; init; } = 64 * 1024;
}

/// <summary>
/// Stateless <see cref="IChatClient"/> adapter over the local Codex Python SDK.
/// ChatGPT authentication is owned by the Codex runtime; prompts and responses
/// travel as UTF-8 JSON over redirected standard input and output.
/// </summary>
public sealed class CodexSdkChatClient : IChatClient, IAsyncDisposable
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true
    };

    private readonly string _model;
    private readonly string _pythonExecutable;
    private readonly string _sidecarScriptPath;
    private readonly string _workingDirectory;
    private readonly string _sandbox;
    private readonly string? _codexExecutable;
    private readonly TimeSpan _requestTimeout;
    private readonly int _maxStandardOutputCharacters;
    private readonly int _maxStandardErrorCharacters;
    private readonly ILogger? _logger;
    private bool _disposed;

    public CodexSdkChatClient(
        string model,
        CodexSdkChatClientOptions? options = null,
        ILogger? logger = null)
    {
        if (string.IsNullOrWhiteSpace(model))
            throw new ArgumentNullException(nameof(model));

        options ??= new CodexSdkChatClientOptions();
        if (string.IsNullOrWhiteSpace(options.PythonExecutable))
            throw new ArgumentException("Python executable must be configured.", nameof(options));
        if (string.IsNullOrWhiteSpace(options.SidecarScriptPath))
            throw new ArgumentException("Sidecar script path must be configured.", nameof(options));
        if (string.IsNullOrWhiteSpace(options.WorkingDirectory))
            throw new ArgumentException("Working directory must be configured.", nameof(options));
        if (options.RequestTimeout <= TimeSpan.Zero)
            throw new ArgumentOutOfRangeException(nameof(options), "Request timeout must be positive.");
        if (options.MaxStandardOutputCharacters <= 0 || options.MaxStandardErrorCharacters <= 0)
            throw new ArgumentOutOfRangeException(nameof(options), "Output limits must be positive.");
        if (options.Sandbox is not ("read-only" or "workspace-write"))
            throw new ArgumentException("Sandbox must be read-only or workspace-write.", nameof(options));

        _model = model;
        _pythonExecutable = options.PythonExecutable;
        _sidecarScriptPath = ResolveSidecarScriptPath(options.SidecarScriptPath);
        _workingDirectory = Path.GetFullPath(options.WorkingDirectory);
        _sandbox = options.Sandbox;
        _codexExecutable = string.IsNullOrWhiteSpace(options.CodexExecutable)
            ? null
            : options.CodexExecutable;
        _requestTimeout = options.RequestTimeout;
        _maxStandardOutputCharacters = options.MaxStandardOutputCharacters;
        _maxStandardErrorCharacters = options.MaxStandardErrorCharacters;
        _logger = logger;

        if (!File.Exists(_sidecarScriptPath))
            throw new FileNotFoundException("Codex SDK sidecar script was not found.", _sidecarScriptPath);
        if (!Directory.Exists(_workingDirectory))
            throw new DirectoryNotFoundException(
                $"Codex SDK working directory was not found: {_workingDirectory}");
    }

    public ChatClientMetadata Metadata => new(nameof(CodexSdkChatClient), null, _model);

    public async Task<ChatResponse> GetResponseAsync(
        IEnumerable<AIChatMessage> messages,
        ChatOptions? options = null,
        CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        var request = BuildRequest(messages, options?.ModelId ?? _model);
        var payload = JsonSerializer.Serialize(request, JsonOptions);
        var response = await RunSidecarAsync(payload, cancellationToken);

        if (!response.Ok)
        {
            var code = response.Error?.Code ?? "unknown_error";
            var message = response.Error?.Message ?? "Codex SDK sidecar failed without an error message.";
            throw new InvalidOperationException($"Codex SDK sidecar error ({code}): {message}");
        }

        if (string.IsNullOrWhiteSpace(response.Text))
            throw new InvalidOperationException("Codex SDK sidecar returned an empty response.");

        _logger?.LogDebug(
            "CodexSdkChatClient received {Length} chars from model {Model}",
            response.Text.Length,
            request.Model);

        return new ChatResponse(new AIChatMessage(ChatRole.Assistant, response.Text));
    }

    public async IAsyncEnumerable<ChatResponseUpdate> GetStreamingResponseAsync(
        IEnumerable<AIChatMessage> messages,
        ChatOptions? options = null,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        var response = await GetResponseAsync(messages, options, cancellationToken);
        var text = response.Messages.FirstOrDefault()?.Text;
        if (!string.IsNullOrEmpty(text))
        {
            yield return new ChatResponseUpdate
            {
                Role = ChatRole.Assistant,
                Contents = [new TextContent(text)]
            };
        }
    }

    public object? GetService(Type serviceType, object? serviceKey = null) =>
        serviceKey is null && serviceType == typeof(ChatClientMetadata)
            ? Metadata
            : null;

    public void Dispose() => _disposed = true;

    public ValueTask DisposeAsync()
    {
        Dispose();
        return ValueTask.CompletedTask;
    }

    private SidecarRequest BuildRequest(IEnumerable<AIChatMessage> messages, string model)
    {
        if (string.IsNullOrWhiteSpace(model))
            throw new InvalidOperationException("Codex SDK model ID must not be empty.");

        var systemPrompt = new StringBuilder();
        var conversation = new StringBuilder();

        foreach (var message in messages)
        {
            var text = message.Text;
            if (string.IsNullOrWhiteSpace(text))
                continue;

            if (message.Role == ChatRole.System)
            {
                if (systemPrompt.Length > 0)
                    systemPrompt.AppendLine().AppendLine();
                systemPrompt.Append(text);
                continue;
            }

            if (conversation.Length > 0)
                conversation.AppendLine().AppendLine();
            conversation.Append('[')
                .Append(message.Role.ToString().ToUpperInvariant())
                .AppendLine("]")
                .Append(text);
        }

        if (conversation.Length == 0)
            throw new InvalidOperationException("Cannot send an empty prompt to Codex SDK.");

        return new SidecarRequest(
            model,
            conversation.ToString(),
            systemPrompt.Length == 0 ? null : systemPrompt.ToString(),
            _workingDirectory,
            _sandbox,
            _codexExecutable);
    }

    private async Task<SidecarResponse> RunSidecarAsync(
        string payload,
        CancellationToken cancellationToken)
    {
        using var process = new Process
        {
            StartInfo = new ProcessStartInfo
            {
                FileName = _pythonExecutable,
                UseShellExecute = false,
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
                WorkingDirectory = _workingDirectory,
                StandardInputEncoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false),
                StandardOutputEncoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false),
                StandardErrorEncoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false)
            }
        };
        process.StartInfo.ArgumentList.Add("-u");
        process.StartInfo.ArgumentList.Add(_sidecarScriptPath);
        process.StartInfo.Environment["PYTHONUTF8"] = "1";
        process.StartInfo.Environment["PYTHONIOENCODING"] = "utf-8";

        try
        {
            if (!process.Start())
                throw new InvalidOperationException("Codex SDK sidecar process did not start.");
        }
        catch (Exception exc) when (exc is InvalidOperationException or System.ComponentModel.Win32Exception)
        {
            throw new InvalidOperationException(
                $"Failed to start the Codex SDK sidecar with '{_pythonExecutable}'.", exc);
        }

        var stdoutTask = ReadBoundedAsync(
            process.StandardOutput,
            _maxStandardOutputCharacters,
            "standard output");
        var stderrTask = ReadBoundedAsync(
            process.StandardError,
            _maxStandardErrorCharacters,
            "standard error");
        KillOnFault(stdoutTask, process);
        KillOnFault(stderrTask, process);

        using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutCts.CancelAfter(_requestTimeout);

        try
        {
            try
            {
                await process.StandardInput.WriteAsync(payload.AsMemory(), timeoutCts.Token);
                await process.StandardInput.FlushAsync(timeoutCts.Token);
                process.StandardInput.Close();
                await process.WaitForExitAsync(timeoutCts.Token);
            }
            catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
            {
                TryKill(process);
                throw new TimeoutException(
                    $"Codex SDK sidecar did not respond within {_requestTimeout.TotalSeconds:0} seconds. " +
                    "Verify ChatGPT authentication with 'codex login status'.");
            }
            catch (OperationCanceledException)
            {
                TryKill(process);
                throw;
            }

            var standardOutput = await stdoutTask;
            var standardError = await stderrTask;
            _logger?.LogDebug(
                "Codex SDK sidecar exited with code {ExitCode}; stderr length {ErrorLength}",
                process.ExitCode,
                standardError.Length);

            SidecarResponse? response;
            try
            {
                response = JsonSerializer.Deserialize<SidecarResponse>(standardOutput, JsonOptions);
            }
            catch (JsonException exc)
            {
                throw new InvalidOperationException(
                    $"Codex SDK sidecar returned invalid JSON (exit code {process.ExitCode}).", exc);
            }

            if (response is null)
                throw new InvalidOperationException(
                    $"Codex SDK sidecar returned no JSON response (exit code {process.ExitCode}).");
            if (process.ExitCode != 0 && response.Ok)
                throw new InvalidOperationException(
                    $"Codex SDK sidecar returned success with exit code {process.ExitCode}.");

            return response;
        }
        finally
        {
            if (!process.HasExited)
                TryKill(process);
        }
    }

    private static async Task<string> ReadBoundedAsync(
        StreamReader reader,
        int maximumCharacters,
        string streamName)
    {
        var result = new StringBuilder(Math.Min(maximumCharacters, 8_192));
        var buffer = new char[8_192];

        while (true)
        {
            var count = await reader.ReadAsync(buffer.AsMemory());
            if (count == 0)
                return result.ToString();
            if (result.Length + count > maximumCharacters)
                throw new InvalidOperationException(
                    $"Codex SDK sidecar {streamName} exceeded {maximumCharacters} characters.");
            result.Append(buffer, 0, count);
        }
    }

    private static void KillOnFault(Task task, Process process)
    {
        _ = task.ContinueWith(
            _ => TryKill(process),
            CancellationToken.None,
            TaskContinuationOptions.OnlyOnFaulted,
            TaskScheduler.Default);
    }

    private static void TryKill(Process process)
    {
        try
        {
            if (!process.HasExited)
                process.Kill(entireProcessTree: true);
        }
        catch (InvalidOperationException)
        {
            // The process exited between the state check and Kill.
        }
        catch (System.ComponentModel.Win32Exception)
        {
            // Best effort during cancellation, timeout, or output-limit failure.
        }
    }

    private static string ResolveSidecarScriptPath(string configuredPath)
    {
        if (Path.IsPathRooted(configuredPath))
            return Path.GetFullPath(configuredPath);

        var outputCandidate = Path.GetFullPath(configuredPath, AppContext.BaseDirectory);
        if (File.Exists(outputCandidate))
            return outputCandidate;

        return Path.GetFullPath(configuredPath, Directory.GetCurrentDirectory());
    }

    private sealed record SidecarRequest(
        string Model,
        string Prompt,
        string? SystemPrompt,
        string WorkingDirectory,
        string Sandbox,
        string? CodexExecutable);

    private sealed record SidecarResponse(
        bool Ok,
        string? Text,
        string? Status,
        SidecarError? Error);

    private sealed record SidecarError(string Code, string Message);
}

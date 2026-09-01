using CobolToQuarkusMigration.Agents.Infrastructure;
using FluentAssertions;
using Microsoft.Extensions.AI;
using Xunit;

using AIChatMessage = Microsoft.Extensions.AI.ChatMessage;

namespace CobolToQuarkusMigration.Tests.Agents.Infrastructure;

public sealed class CodexSdkChatClientTests
{
    [Fact]
    public async Task GetResponseAsync_UsesJsonStdinWithoutApiKey()
    {
        using var client = CreateClient();
        var messages = new[]
        {
            new AIChatMessage(ChatRole.System, "Return text."),
            new AIChatMessage(ChatRole.User, "hello; echo must-not-run")
        };

        var response = await client.GetResponseAsync(messages);
        var text = response.Messages.Single().Text;

        text.Should().Contain("model=gpt-5.4");
        text.Should().Contain("sandbox=read-only");
        text.Should().Contain("hello; echo must-not-run");
        text.Should().Contain("hasApiKey=False");
    }

    [Fact]
    public async Task GetResponseAsync_PropagatesStructuredSidecarFailure()
    {
        using var client = CreateClient();
        var messages = new[] { new AIChatMessage(ChatRole.User, "fail") };

        var act = () => client.GetResponseAsync(messages);

        await act.Should().ThrowAsync<InvalidOperationException>()
            .WithMessage("*fake_failure*expected failure*");
    }

    [Fact]
    public async Task GetResponseAsync_TimesOutAndTerminatesSidecar()
    {
        using var client = CreateClient(TimeSpan.FromMilliseconds(100));
        var messages = new[] { new AIChatMessage(ChatRole.User, "sleep") };

        var act = () => client.GetResponseAsync(messages);

        await act.Should().ThrowAsync<TimeoutException>()
            .WithMessage("*did not respond*");
    }

    [Fact]
    public async Task GetResponseAsync_TimesOutWhenSidecarDoesNotReadStandardInput()
    {
        var options = CreateOptions(TimeSpan.FromMilliseconds(100)) with
        {
            SidecarScriptPath = Path.Combine(
                AppContext.BaseDirectory,
                "TestAssets",
                "fake_nonreading_sidecar.py")
        };
        using var client = new CodexSdkChatClient("gpt-5.4", options);
        var largePrompt = new string('x', 1024 * 1024);

        var act = () => client.GetResponseAsync(
            new[] { new AIChatMessage(ChatRole.User, largePrompt) });

        await act.Should().ThrowAsync<TimeoutException>()
            .WithMessage("*did not respond*");
    }

    [Fact]
    public async Task GetResponseAsync_WhenDisposed_ThrowsObjectDisposedException()
    {
        var client = CreateClient();
        client.Dispose();

        var act = () => client.GetResponseAsync(
            new[] { new AIChatMessage(ChatRole.User, "hello") });

        await act.Should().ThrowAsync<ObjectDisposedException>();
    }

    [Fact]
    public void Constructor_RejectsFullAccessSandbox()
    {
        var options = CreateOptions(TimeSpan.FromSeconds(5)) with
        {
            Sandbox = "full-access"
        };

        var act = () => new CodexSdkChatClient("gpt-5.4", options);

        act.Should().Throw<ArgumentException>()
            .WithMessage("*read-only or workspace-write*");
    }

    [Theory]
    [InlineData("OpenAI", "OpenAI")]
    [InlineData("CodexSDK", "Codex SDK")]
    [InlineData("GitHubCopilotSDK", "GitHub Copilot")]
    [InlineData("AzureOpenAI", "Azure OpenAI")]
    public void GetProviderName_PreservesConfiguredProvider(string serviceType, string expected)
    {
        ChatClientFactory.GetProviderName(null, serviceType).Should().Be(expected);
    }

    [Fact]
    public void GetService_ReturnsMetadataOnlyForUnkeyedMetadataRequest()
    {
        using var client = CreateClient();

        client.GetService(typeof(ChatClientMetadata)).Should().BeEquivalentTo(client.Metadata);
        client.GetService(typeof(ChatClientMetadata), "someKey").Should().BeNull();
        client.GetService(typeof(IChatClient)).Should().BeNull();
    }

    private static CodexSdkChatClient CreateClient(TimeSpan? timeout = null) =>
        new("gpt-5.4", CreateOptions(timeout ?? TimeSpan.FromSeconds(5)));

    private static CodexSdkChatClientOptions CreateOptions(TimeSpan timeout) =>
        new()
        {
            PythonExecutable = OperatingSystem.IsWindows() ? "python" : "python3",
            SidecarScriptPath = Path.Combine(
                AppContext.BaseDirectory,
                "TestAssets",
                "fake_codex_sidecar.py"),
            WorkingDirectory = AppContext.BaseDirectory,
            Sandbox = "read-only",
            RequestTimeout = timeout
        };
}

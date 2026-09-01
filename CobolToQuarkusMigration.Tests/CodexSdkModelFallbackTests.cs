using CobolToQuarkusMigration.Models;
using FluentAssertions;
using Xunit;

namespace CobolToQuarkusMigration.Tests;

public sealed class CodexSdkModelFallbackTests
{
    [Fact]
    public void PrimaryModel_ReplacesAzureDefaults_WhenSpecificOverridesAreAbsent()
    {
        var settings = CreateSettings("CodexSDK");

        Program.ApplyCodexSdkPrimaryModel(settings, "gpt-5.6-terra");

        settings.DeploymentName.Should().Be("gpt-5.6-terra");
        settings.ChatModelId.Should().Be("gpt-5.6-terra");
        settings.ChatDeploymentName.Should().Be("gpt-5.6-terra");
        settings.CobolAnalyzerModelId.Should().Be("gpt-5.6-terra");
        settings.JavaConverterModelId.Should().Be("gpt-5.6-terra");
        settings.DependencyMapperModelId.Should().Be("gpt-5.6-terra");
        settings.UnitTestModelId.Should().Be("gpt-5.6-terra");
    }

    [Fact]
    public void NonCodexProvider_IsUnchanged()
    {
        var settings = CreateSettings("AzureOpenAI");

        Program.ApplyCodexSdkPrimaryModel(settings, "gpt-5.6-terra");

        settings.ChatModelId.Should().Be("azure-chat-default");
        settings.CobolAnalyzerModelId.Should().Be("azure-code-default");
    }

    private static AISettings CreateSettings(string serviceType) => new()
    {
        ServiceType = serviceType,
        ModelId = "azure-code-default",
        DeploymentName = "azure-code-default",
        ChatModelId = "azure-chat-default",
        ChatDeploymentName = "azure-chat-default",
        CobolAnalyzerModelId = "azure-code-default",
        JavaConverterModelId = "azure-code-default",
        DependencyMapperModelId = "azure-code-default",
        UnitTestModelId = "azure-code-default"
    };
}

using CobolToQuarkusMigration.Agents;
using FluentAssertions;
using Xunit;

namespace CobolToQuarkusMigration.Tests.Agents;

public class DependencyMapperAgentTests
{
    [Fact]
    public void FindCopybookReferenceLine_CopyStatement_ReturnsOneBasedSourceLine()
    {
        var source = """
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REPORT.
            DATA DIVISION.
            COPY CUSTOMER-DATA.
            PROCEDURE DIVISION.
            """;

        DependencyMapperAgent.FindCopybookReferenceLine(source, "CUSTOMER-DATA.cpy")
            .Should().Be(4);
    }

    [Fact]
    public void FindCopybookReferenceLine_QuotedIncludeWithCrLf_ReturnsOneBasedSourceLine()
    {
        var source = "IDENTIFICATION DIVISION.\r\n" +
                     "PROGRAM-ID. REPORT.\r\n" +
                     "DATA DIVISION.\r\n" +
                     "INCLUDE 'CUSTOMER-DATA'.\r\n";

        DependencyMapperAgent.FindCopybookReferenceLine(source, "customer-data.cpy")
            .Should().Be(4);
    }

    [Fact]
    public void FindCopybookReferenceLine_MissingReference_ReturnsZero()
    {
        DependencyMapperAgent.FindCopybookReferenceLine(
                "COPY OTHER-DATA.",
                "CUSTOMER-DATA.cpy")
            .Should().Be(0);
    }

    [Fact]
    public void FindCopybookReferenceLine_CommentedReference_UsesExecutableStatement()
    {
        var source = "      * COPY CUSTOMER-DATA.\n" +
                     "       COPY CUSTOMER-DATA.\n";

        DependencyMapperAgent.FindCopybookReferenceLine(source, "CUSTOMER-DATA.cpy")
            .Should().Be(2);
    }
}

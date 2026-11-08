namespace OregonGeographyGame.Models;

/// <summary>
/// The outcome of one Counties-mode round. A pass is a round where the
/// piece was never placed: <see cref="OverlapFraction"/> is null and
/// <see cref="Points"/> is 0.
/// </summary>
public sealed record CountyRoundResult(
    string CountyName,
    double? OverlapFraction,
    int Points);

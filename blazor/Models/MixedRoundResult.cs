namespace OregonGeographyGame.Models;

/// <summary>
/// The outcome of one City County Mode round. City rounds carry the
/// distance (null on a pass); county rounds carry the selected county
/// name and whether it was correct (null selection on a pass).
/// County questions are worth 100 points for a correct pick — like a city
/// round, and unlike "Name the county" mode, which is 1 point.
/// </summary>
public sealed record MixedRoundResult(
    MixedRound Round,
    double? DistanceMiles,
    string? SelectedCountyName,
    bool? IsCorrect,
    int Points);

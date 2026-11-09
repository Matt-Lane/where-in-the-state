namespace OregonGeographyGame.Models;

/// <summary>
/// The outcome of one City County Mode round. City rounds carry the
/// distance (null on a pass); county rounds carry the selected county
/// name and whether it was correct (null selection on a pass).
/// County questions are worth 100 points for a correct pick, 50 for a
/// county sharing a border with the named one (<see cref="IsAdjacent"/>),
/// 0 otherwise. See GAME-SPEC §6.6.
/// </summary>
public sealed record MixedRoundResult(
    MixedRound Round,
    double? DistanceMiles,
    string? SelectedCountyName,
    bool? IsCorrect,
    bool IsAdjacent,
    int Points);

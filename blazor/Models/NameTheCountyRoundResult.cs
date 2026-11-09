namespace OregonGeographyGame.Models;

/// <summary>
/// The outcome of one "Name the county" round. A pass is a round where no
/// county was selected: <see cref="SelectedCountyName"/> is null,
/// <see cref="IsCorrect"/> is false and <see cref="Points"/> is 0.
/// Scoring: naming the right county is 100 points, a county sharing a
/// border with it is 50 (<see cref="IsAdjacent"/>), any other county (or
/// a pass) is 0. See GAME-SPEC §6.5.
/// </summary>
public sealed record NameTheCountyRoundResult(
    string CountyName,
    string? SelectedCountyName,
    bool IsCorrect,
    bool IsAdjacent,
    int Points);

namespace OregonGeographyGame.Models;

/// <summary>
/// The outcome of one round. A pass is a round with no pin placed:
/// <see cref="GuessLatitude"/> / <see cref="GuessLongitude"/> and
/// <see cref="DistanceMiles"/> are null and <see cref="Points"/> is 0.
/// </summary>
public sealed record RoundResult(
    City City,
    double? GuessLatitude,
    double? GuessLongitude,
    double? DistanceMiles,
    int Points);

namespace OregonGeographyGame.Services;

/// <summary>Haversine distance (miles) and the per-round scoring rule.</summary>
public sealed class DistanceService
{
    private const double EarthRadiusMiles = 3959.0;

    public static double HaversineMiles(double lat1, double lon1, double lat2, double lon2)
    {
        double dLat = DegreesToRadians(lat2 - lat1);
        double dLon = DegreesToRadians(lon2 - lon1);
        double a = Math.Sin(dLat / 2) * Math.Sin(dLat / 2)
            + Math.Cos(DegreesToRadians(lat1)) * Math.Cos(DegreesToRadians(lat2))
            * Math.Sin(dLon / 2) * Math.Sin(dLon / 2);
        // Floating-point rounding can push a a hair above 1 for very long
        // distances, and Asin(Sqrt(a)) is NaN then. Clamp to [0, 1].
        a = Math.Min(1.0, Math.Max(0.0, a));
        return 2 * EarthRadiusMiles * Math.Asin(Math.Sqrt(a));
    }

    /// <summary>
    /// Scoring (GAME-SPEC.md §6, updated): full 100 points when the
    /// rounded distance is 5 miles or less, then −1 point per mile
    /// beyond 5, floored at 0. So 5 mi = 100, 6 mi = 99, 10 mi = 95,
    /// 55 mi = 50, 105+ mi = 0. Never negative.
    /// Points use the *rounded* whole-mile distance, so the displayed
    /// distance (1 decimal) and the points always agree.
    /// </summary>
    public static int ScoreForDistance(double miles)
    {
        // A non-finite distance (NaN/Infinity) can never be a real guess;
        // score it 0 instead of letting (int)Math.Round(NaN) produce a
        // nonsense value.
        if (!double.IsFinite(miles))
        {
            return 0;
        }

        int rounded = (int)Math.Round(miles);
        return rounded <= 5 ? 100 : Math.Max(0, 100 - (rounded - 5));
    }

    private static double DegreesToRadians(double degrees) => degrees * Math.PI / 180.0;
}

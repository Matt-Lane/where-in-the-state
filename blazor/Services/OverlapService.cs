namespace OregonGeographyGame.Services;

/// <summary>
/// Overlap scoring for Counties mode: how much of the true county the
/// placed piece covers.
/// <para>
/// The placed piece is the true county translated by (<paramref name="dx"/>,
/// <paramref name="dy"/>) in SVG viewBox units, so the overlap is computed
/// on a grid in SVG space. The projection is a linear (affine) map, so area
/// ratios in SVG space equal area ratios on the ground, and point-in-polygon
/// is preserved. Working in SVG space also means the placed piece never has
/// to be converted back to lat/lon.
/// </para>
/// <para>
/// Grid sampling (rather than exact polygon clipping) keeps this dependency-free
/// and identical in the Blazor and standalone JS versions: for each grid cell
/// centre, test whether it is inside the true county and inside the placed
/// piece. With a 4-unit grid step the overlap is accurate to well under a
/// point. Only cells inside the true county's bounding box are tested.
/// </para>
/// </summary>
public static class OverlapService
{
    /// <summary>Grid step in SVG viewBox units (the viewBox is 1000 × 757.4).</summary>
    private const double GridStep = 4.0;

    /// <summary>
    /// The fraction of the true county's area covered by the placed piece,
    /// in [0, 1]. <paramref name="trueRingsSvg"/> is the county's rings in
    /// SVG coordinates (outer rings only; counties have no holes). The placed
    /// piece is those same rings translated by (<paramref name="dx"/>,
    /// <paramref name="dy"/>).
    /// </summary>
    public static double OverlapFraction(
        IReadOnlyList<IReadOnlyList<(double X, double Y)>> trueRingsSvg,
        double dx, double dy)
    {
        if (trueRingsSvg.Count == 0)
        {
            return 0;
        }

        // Bounding box of the true county, in SVG units.
        double minX = double.MaxValue, minY = double.MaxValue;
        double maxX = double.MinValue, maxY = double.MinValue;
        foreach (var ring in trueRingsSvg)
        {
            foreach (var (x, y) in ring)
            {
                minX = Math.Min(minX, x); maxX = Math.Max(maxX, x);
                minY = Math.Min(minY, y); maxY = Math.Max(maxY, y);
            }
        }

        int insideTrue = 0;
        int insideBoth = 0;
        // Cell centres, so a cell on the boundary counts half the time —
        // the error this introduces is far below a point at this grid size.
        for (double y = minY + GridStep / 2; y <= maxY; y += GridStep)
        {
            for (double x = minX + GridStep / 2; x <= maxX; x += GridStep)
            {
                if (!IsInsideAnyRing(x, y, trueRingsSvg))
                {
                    continue;
                }

                insideTrue++;
                // The placed piece is the true county translated by (dx, dy),
                // so a point is inside the placed piece exactly when the point
                // shifted back by (dx, dy) is inside the true county.
                if (IsInsideAnyRing(x - dx, y - dy, trueRingsSvg))
                {
                    insideBoth++;
                }
            }
        }

        return insideTrue == 0 ? 0 : (double)insideBoth / insideTrue;
    }

    /// <summary>
    /// Points for an overlap fraction: 100 for a perfect placement, scaled
    /// linearly, floored at 0. Mirrors the city game's /100 per round so the
    /// two modes share a /1000 game total.
    /// </summary>
    public static int ScoreForOverlap(double overlap)
    {
        if (!double.IsFinite(overlap))
        {
            return 0;
        }

        return (int)Math.Round(Math.Clamp(overlap, 0, 1) * 100);
    }

    /// <summary>True when the point is inside any of the rings (ray casting).</summary>
    internal static bool IsInsideAnyRing(
        double x, double y,
        IReadOnlyList<IReadOnlyList<(double X, double Y)>> rings)
    {
        foreach (var ring in rings)
        {
            if (IsInsideRing(x, y, ring))
            {
                return true;
            }
        }

        return false;
    }

    private static bool IsInsideRing(double x, double y, IReadOnlyList<(double X, double Y)> ring)
    {
        bool inside = false;
        int n = ring.Count;
        for (int i = 0; i < n; i++)
        {
            var (x1, y1) = ring[i];
            var (x2, y2) = ring[(i + 1) % n];
            if ((y1 > y) != (y2 > y))
            {
                double xin = (x2 - x1) * (y - y1) / (y2 - y1) + x1;
                if (x < xin)
                {
                    inside = !inside;
                }
            }
        }

        return inside;
    }
}

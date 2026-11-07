namespace OregonGeographyGame.Services;

/// <summary>
/// Equirectangular projection with a cos(44°) correction, for Oregon.
/// <para>
/// <b>The same formulas must be used both ways.</b>
/// <see cref="LatLonToSvg"/> draws the map and <see cref="SvgToLatLon"/>
/// converts a click back to lat/lon; they are exact inverses of each
/// other, so a click on a drawn feature converts back to that feature's
/// coordinates. If the drawing and click conversions ever diverge, clicks
/// and the drawn outline silently disagree and scoring breaks.
/// </para>
/// <para>
/// The cos(44°) factor corrects for longitude degrees being shorter than
/// latitude degrees at Oregon's latitude (~44° N). The scale is chosen so
/// the longitude span fills the 1000-unit viewBox width; the resulting
/// viewBox height is (LatMax − LatMin) × Scale ≈ 757.4.
/// </para>
/// <para>
/// Bounds are the Oregon pack bounds from <c>state.json</c> (with a small
/// margin): lon −124.716 to −116.314, lat 41.843 to 46.421. Other state
/// packs will need their own bounds/projection constants — this class is
/// the Oregon instance of the projection; a future generic version should
/// take the bounds as constructor parameters instead of constants.
/// </para>
/// </summary>
public static class MapProjection
{
    public const double LonMin = -124.716;
    public const double LonMax = -116.314;
    public const double LatMin = 41.843;
    public const double LatMax = 46.421;

    /// <summary>cos(44°): longitude degrees are ~0.719× latitude degrees at 44° N.</summary>
    public static readonly double Cos44 = Math.Cos(44 * Math.PI / 180.0);

    public const double ViewBoxWidth = 1000.0;

    /// <summary>
    /// 757.4 — the viewBox height per the spec. Exact arithmetic gives
    /// (LatMax − LatMin) × Scale ≈ 757.46; the 0.06-unit difference is
    /// negligible (0.008% of the height) and both projection directions
    /// use <see cref="Scale"/>, so they remain exact inverses.
    /// </summary>
    public const double ViewBoxHeight = 757.4;

    /// <summary>SVG units per degree of latitude: 1000 / ((LonMax − LonMin) × Cos44).</summary>
    public static readonly double Scale = ViewBoxWidth / ((LonMax - LonMin) * Cos44);

    /// <summary>Geographic coordinates → SVG viewBox coordinates.</summary>
    public static (double X, double Y) LatLonToSvg(double latitude, double longitude)
    {
        double x = (longitude - LonMin) * Cos44 * Scale;
        double y = (LatMax - latitude) * Scale;
        return (x, y);
    }

    /// <summary>
    /// SVG viewBox coordinates → geographic coordinates.
    /// The exact inverse of <see cref="LatLonToSvg"/>: the same
    /// <see cref="Cos44"/> and <see cref="Scale"/> appear in both.
    /// </summary>
    public static (double Latitude, double Longitude) SvgToLatLon(double x, double y)
    {
        double longitude = LonMin + x / (Cos44 * Scale);
        double latitude = LatMax - y / Scale;
        return (latitude, longitude);
    }
}

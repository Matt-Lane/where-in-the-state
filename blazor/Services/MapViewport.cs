namespace OregonGeographyGame.Services;

/// <summary>
/// The visible window onto the map: a sub-rectangle of the full viewBox
/// (0 0 1000 757.4). The SVG's viewBox attribute is bound to it, and the
/// Confirm bubble and the Reset button read it.
/// <para>
/// The live gesture (pinch/pan) is owned entirely by JavaScript (see
/// mapGesture in index.html): it eases the displayed window toward the
/// fingers' target and writes the SVG viewBox attribute directly, so a
/// gesture never pays a Blazor re-render or a JS interop round-trip per
/// frame. This class holds the SYNCED window — the final viewBox a
/// gesture ends at (see <see cref="SyncTo"/>) — which is what taps
/// resolve against and what the Reset button reads. Blazor sets it on
/// round/reveal/reset (<see cref="Reset"/>) and JavaScript reports the
/// final window when a gesture ends; the two are kept identical, so the
/// DOM viewBox and this window never disagree.
/// </para>
/// <para>
/// The easing math (0.35 per frame, 0.05 settle epsilon, 250 minimum
/// width, 10 px tap threshold, incremental pinch ratio, map clamp) lives
/// in the JS controller now, mirroring the standalone version's vb*
/// helpers.
/// </para>
/// </summary>
public sealed class MapViewport
{
    public const double FullWidth = MapProjection.ViewBoxWidth;
    public const double FullHeight = MapProjection.ViewBoxHeight;

    /// <summary>Maximum zoom-in: 4×, so a player can zoom into a city area but not to a useless extreme.</summary>
    public const double MinWidth = 250.0;

    public double X { get; private set; }
    public double Y { get; private set; }
    public double Width { get; private set; } = FullWidth;
    public double Height { get; private set; } = FullHeight;

    public bool IsZoomed => Width < FullWidth - 0.5;

    /// <summary>The SVG viewBox attribute value for the current window.</summary>
    public string ViewBox => $"{X:F1} {Y:F1} {Width:F1} {Height:F1}";

    /// <summary>Back to the full map.</summary>
    public void Reset()
    {
        X = 0;
        Y = 0;
        Width = FullWidth;
        Height = FullHeight;
    }

    /// <summary>
    /// Set the window to the final viewBox a gesture ended at, as reported
    /// by the JS controller. The height follows the width (same aspect as
    /// the full viewBox) and the window is clamped to the map, so a sync
    /// can never leave the window out of bounds.
    /// </summary>
    public void SyncTo(double x, double y, double width)
    {
        Width = Math.Clamp(width, MinWidth, FullWidth);
        Height = Width * FullHeight / FullWidth;
        X = Math.Clamp(x, 0, FullWidth - Width);
        Y = Math.Clamp(y, 0, FullHeight - Height);
    }

    /// <summary>
    /// Client (CSS pixel) coordinates → SVG viewBox coordinates in the
    /// current window. rectLeft/Top/Width/Height are the SVG element's
    /// bounding rect from getBoundingClientRect.
    /// </summary>
    public (double X, double Y) ClientToSvg(double clientX, double clientY,
        double rectLeft, double rectTop, double rectWidth, double rectHeight)
    {
        return (
            X + (clientX - rectLeft) * Width / rectWidth,
            Y + (clientY - rectTop) * Height / rectHeight);
    }

    /// <summary>True when an SVG point is inside the current window (for the Confirm bubble).</summary>
    public bool Contains(double svgX, double svgY)
        => svgX >= X && svgX <= X + Width && svgY >= Y && svgY <= Y + Height;

    /// <summary>
    /// An SVG point as a percentage of the current window — the Confirm
    /// bubble is positioned in percentages of the map wrapper, which is
    /// exactly the SVG's box, so it tracks the pin at any zoom/pan.
    /// </summary>
    public (double LeftPct, double TopPct) ToPercent(double svgX, double svgY)
        => ((svgX - X) / Width * 100.0, (svgY - Y) / Height * 100.0);
}

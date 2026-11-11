namespace OregonGeographyGame.Services;

/// <summary>
/// The visible window onto the map: a sub-rectangle of the full viewBox
/// (0 0 1000 757.4). Pinch-to-zoom and pan move this window; the SVG's
/// viewBox attribute is bound to it, so the map re-renders zoomed/panned
/// with no other drawing changes. All conversions between client (CSS
/// pixel) coordinates and SVG viewBox coordinates go through here, so a
/// tap always resolves against the CURRENT view — never the full map.
/// <para>
/// Zoom keeps the viewBox aspect ratio (1000 / 757.4) and clamps to the
/// map bounds, so the window never shows area outside the state.
/// </para>
/// </summary>
public sealed class MapViewport
{
    public const double FullWidth = MapProjection.ViewBoxWidth;
    public const double FullHeight = MapProjection.ViewBoxHeight;

    /// <summary>Maximum zoom-in: 4×, so a player can zoom into a city area but not to a useless extreme.</summary>
    public const double MinWidth = 250.0;

    /// <summary>Movement under this many CSS pixels still counts as a tap, not a drag/pan.</summary>
    public const double TapMoveThresholdPx = 10.0;

    public double X { get; private set; }
    public double Y { get; private set; }
    public double Width { get; private set; } = FullWidth;
    public double Height { get; private set; } = FullHeight;

    /// <summary>True once the player has zoomed in past the full map.</summary>
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
    /// Client (CSS pixel) coordinates → SVG viewBox coordinates in the
    /// CURRENT window. rectLeft/Top/Width/Height are the SVG element's
    /// bounding rect from getBoundingClientRect.
    /// </summary>
    public (double X, double Y) ClientToSvg(double clientX, double clientY,
        double rectLeft, double rectTop, double rectWidth, double rectHeight)
    {
        return (
            X + (clientX - rectLeft) * Width / rectWidth,
            Y + (clientY - rectTop) * Height / rectHeight);
    }

    /// <summary>
    /// Zoom so the SVG point under the given client anchor stays under it.
    /// newWidth is clamped to [MinWidth, FullWidth]; the height follows
    /// from the fixed aspect ratio, and the window is clamped to the map.
    /// </summary>
    public void ZoomAt(double anchorSvgX, double anchorSvgY,
        double anchorClientX, double anchorClientY,
        double rectLeft, double rectTop, double rectWidth, double rectHeight,
        double newWidth)
    {
        newWidth = Math.Clamp(newWidth, MinWidth, FullWidth);
        double newHeight = newWidth * FullHeight / FullWidth;
        double newX = anchorSvgX - (anchorClientX - rectLeft) * newWidth / rectWidth;
        double newY = anchorSvgY - (anchorClientY - rectTop) * newHeight / rectHeight;
        Width = newWidth;
        Height = newHeight;
        X = Math.Clamp(newX, 0, FullWidth - newWidth);
        Y = Math.Clamp(newY, 0, FullHeight - newHeight);
    }

    /// <summary>
    /// Pan by a client-pixel delta (drag direction: the map follows the
    /// finger). A no-op at full view — there is nothing to pan to. The
    /// window is clamped to the map bounds.
    /// </summary>
    public void Pan(double dxClient, double dyClient, double rectWidth, double rectHeight)
    {
        if (!IsZoomed)
        {
            return;
        }

        X = Math.Clamp(X - dxClient * Width / rectWidth, 0, FullWidth - Width);
        Y = Math.Clamp(Y - dyClient * Height / rectHeight, 0, FullHeight - Height);
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

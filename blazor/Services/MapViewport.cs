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
/// <para>
/// Smoothing: gestures write to a TARGET window, and the displayed window
/// eases toward it once per animation frame (see <see cref="StepTowardsTarget"/>).
/// The displayed window is what the viewBox shows and what taps resolve
/// against; the target is where the fingers are asking it to go. This
/// makes the zoom track the fingers without their micro-jitter — the
/// displayed window is a low-pass filter on the input — and lets the
/// caller batch viewBox updates to the display refresh instead of
/// re-rendering on every pointermove. When a gesture ends,
/// <see cref="SnapToTarget"/> makes the displayed window exactly the
/// target, so taps and the next gesture start from an exact state.
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

    /// <summary>
    /// How far the displayed window moves toward the target each animation
    /// frame (0.35 closes ~35% of the gap per frame). Responsive enough to
    /// track the fingers closely, small enough to filter out micro-jitter.
    /// </summary>
    public const double EaseFactor = 0.35;

    /// <summary>Below this gap (SVG units) the displayed window snaps to the target.</summary>
    private const double SnapEpsilon = 0.05;

    public double X { get; private set; }
    public double Y { get; private set; }
    public double Width { get; private set; } = FullWidth;
    public double Height { get; private set; } = FullHeight;

    /// <summary>The window the fingers are asking for; the displayed window eases toward it.</summary>
    public double TargetX { get; private set; }
    public double TargetY { get; private set; }
    public double TargetWidth { get; private set; } = FullWidth;
    public double TargetHeight { get; private set; } = FullHeight;

    /// <summary>True once the player has zoomed in past the full map (displayed or target).</summary>
    public bool IsZoomed => Width < FullWidth - 0.5 || TargetWidth < FullWidth - 0.5;

    /// <summary>True while the displayed window is still easing toward the target.</summary>
    public bool IsEasing =>
        Math.Abs(X - TargetX) > SnapEpsilon || Math.Abs(Y - TargetY) > SnapEpsilon ||
        Math.Abs(Width - TargetWidth) > SnapEpsilon || Math.Abs(Height - TargetHeight) > SnapEpsilon;

    /// <summary>The SVG viewBox attribute value for the current (displayed) window.</summary>
    public string ViewBox => $"{X:F1} {Y:F1} {Width:F1} {Height:F1}";

    /// <summary>Back to the full map, displayed and target together (no easing).</summary>
    public void Reset()
    {
        X = 0;
        Y = 0;
        Width = FullWidth;
        Height = FullHeight;
        TargetX = 0;
        TargetY = 0;
        TargetWidth = FullWidth;
        TargetHeight = FullHeight;
    }

    /// <summary>
    /// Client (CSS pixel) coordinates → SVG viewBox coordinates in the
    /// CURRENT (displayed) window. rectLeft/Top/Width/Height are the SVG element's
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
    /// Zoom the TARGET window so the SVG point under the given client anchor
    /// stays under it. newWidth is clamped to [MinWidth, FullWidth]; the height
    /// follows from the fixed aspect ratio, and the window is clamped to the
    /// map. The displayed window eases toward the target (see
    /// <see cref="StepTowardsTarget"/>); it is not set here.
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
        TargetWidth = newWidth;
        TargetHeight = newHeight;
        TargetX = Math.Clamp(newX, 0, FullWidth - newWidth);
        TargetY = Math.Clamp(newY, 0, FullHeight - newHeight);
    }

    /// <summary>
    /// Pan the TARGET window by a client-pixel delta (drag direction: the map
    /// follows the finger). A no-op at full view — there is nothing to pan to.
    /// The window is clamped to the map bounds. The displayed window eases
    /// toward the target (see <see cref="StepTowardsTarget"/>).
    /// </summary>
    public void Pan(double dxClient, double dyClient, double rectWidth, double rectHeight)
    {
        if (TargetWidth >= FullWidth - 0.5)
        {
            return;
        }

        TargetX = Math.Clamp(TargetX - dxClient * TargetWidth / rectWidth, 0, FullWidth - TargetWidth);
        TargetY = Math.Clamp(TargetY - dyClient * TargetHeight / rectHeight, 0, FullHeight - TargetHeight);
    }

    /// <summary>
    /// Move the displayed window one animation frame toward the target.
    /// Returns true if the displayed window changed (so the caller knows to
    /// re-render / schedule another frame). Snaps exactly to the target when
    /// the gap is under the epsilon, so the easing always terminates and the
    /// final state is exact. The displayed window is kept inside the map
    /// bounds while easing.
    /// </summary>
    public bool StepTowardsTarget()
    {
        if (!IsEasing)
        {
            return false;
        }

        X += (TargetX - X) * EaseFactor;
        Y += (TargetY - Y) * EaseFactor;
        Width += (TargetWidth - Width) * EaseFactor;
        Height += (TargetHeight - Height) * EaseFactor;

        if (!IsEasing)
        {
            // Close enough: snap exactly, so the final state is the target.
            X = TargetX;
            Y = TargetY;
            Width = TargetWidth;
            Height = TargetHeight;
        }
        else
        {
            // Safety net: the lerp of two in-bounds windows stays in bounds,
            // but clamp anyway so the displayed window can never show
            // outside the map.
            Width = Math.Clamp(Width, MinWidth, FullWidth);
            Height = Width * FullHeight / FullWidth;
            X = Math.Clamp(X, 0, FullWidth - Width);
            Y = Math.Clamp(Y, 0, FullHeight - Height);
        }

        return true;
    }

    /// <summary>
    /// Make the displayed window exactly the target (gesture end), so taps
    /// and the next gesture start from an exact state.
    /// </summary>
    public void SnapToTarget()
    {
        X = TargetX;
        Y = TargetY;
        Width = TargetWidth;
        Height = TargetHeight;
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

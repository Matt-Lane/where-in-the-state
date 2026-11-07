namespace OregonGeographyGame.Models;

/// <summary>Geographic bounds of a state pack, in degrees.</summary>
public sealed record MapBounds(
    double LonMin,
    double LonMax,
    double LatMin,
    double LatMax);

/// <summary>
/// A toggleable landmark layer (interstates, highways, rivers, lakes).
/// The <see cref="StatePack.Layers"/> list comes from the pack manifest
/// (<c>state.json</c>); it is display metadata only and never affects scoring.
/// </summary>
public sealed record LandmarkLayer(string Id, string Label, bool VisibleByDefault);

/// <summary>
/// One parsed GeoJSON feature, in a shape the map renderer can draw
/// without knowing anything about GeoJSON.
/// <list type="bullet">
///   <item><description><c>Kind</c> is "Polygon" (state outline, lakes) or "Line" (roads, rivers).</description></item>
///   <item><description><c>Parts</c> is a list of rings (Polygon) or lines (Line);
///   each part is an ordered list of (Lon, Lat) points.</description></item>
///   <item><description><c>Layer</c> is the feature's <c>properties.layer</c>
///   value (e.g. "interstate", "highway", "river", "lake", or "outline").</description></item>
/// </list>
/// Coordinates are never invented here — they come verbatim from the
/// pack's GeoJSON files via <see cref="Services.StatePackLoader"/>.
/// </summary>
public sealed record MapFeature(
    string Kind,
    string Layer,
    string? Name,
    IReadOnlyList<IReadOnlyList<(double Lon, double Lat)>> Parts);

/// <summary>
/// A state pack: everything the game needs to play one state.
/// The game logic knows nothing about Oregon (or any other state) — it
/// only knows how to load a <see cref="StatePack"/> and play from it.
/// Swapping states = swapping the pack; no C# changes.
/// </summary>
public sealed record StatePack(
    string Id,              // "oregon"
    string Name,            // "Oregon"
    string Abbreviation,    // "OR"
    IReadOnlyList<City> Cities,
    IReadOnlyList<MapFeature> Outline,
    IReadOnlyList<MapFeature> Landmarks,
    IReadOnlyList<LandmarkLayer> Layers,
    MapBounds Bounds);

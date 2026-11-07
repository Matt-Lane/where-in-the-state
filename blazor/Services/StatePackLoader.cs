using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;
using OregonGeographyGame.Models;

namespace OregonGeographyGame.Services;

/// <summary>
/// Loads a state pack from <c>wwwroot/data/states/&lt;id&gt;/</c>:
/// <c>state.json</c> (manifest), <c>cities.json</c>,
/// <c>outline.geojson</c> and <c>landmarks.geojson</c>.
/// GeoJSON coordinates are parsed with <see cref="System.Text.Json"/>
/// into <see cref="MapFeature"/> values — no coordinates are invented
/// or hard-coded here; the files are the source of truth.
/// </summary>
public sealed class StatePackLoader
{
    private readonly HttpClient _http;

    public StatePackLoader(HttpClient http)
    {
        _http = http;
    }

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true
    };

    /// <summary>Load the index of available state packs (<c>wwwroot/data/states.json</c>).</summary>
    public async Task<IReadOnlyList<StatePackIndexEntry>> LoadStateIndexAsync()
    {
        var entries = await _http.GetFromJsonAsync<List<StatePackIndexEntry>>(
            "data/states.json", JsonOptions);
        return entries ?? [];
    }

    /// <summary>Load one state pack by id (e.g. "oregon").</summary>
    public async Task<StatePack> LoadAsync(string stateId)
    {
        string basePath = $"data/states/{stateId}";

        var manifest = await _http.GetFromJsonAsync<StateManifest>(
            $"{basePath}/state.json", JsonOptions)
            ?? throw new InvalidOperationException($"Missing or invalid {basePath}/state.json.");

        var cities = await _http.GetFromJsonAsync<List<City>>(
            $"{basePath}/{manifest.Files.Cities}", JsonOptions)
            ?? throw new InvalidOperationException($"Missing or invalid {basePath}/{manifest.Files.Cities}.");

        var outline = await LoadGeoJsonAsync($"{basePath}/{manifest.Files.Outline}", layerFallback: "outline");
        var landmarks = await LoadGeoJsonAsync($"{basePath}/{manifest.Files.Landmarks}", layerFallback: null);

        return new StatePack(
            Id: manifest.Id,
            Name: manifest.Name,
            Abbreviation: manifest.Abbreviation,
            Cities: cities,
            Outline: outline,
            Landmarks: landmarks,
            Layers: manifest.Layers.Select(l => new LandmarkLayer(l.Id, l.Label, l.VisibleByDefault)).ToList(),
            Bounds: new MapBounds(manifest.Bounds.LonMin, manifest.Bounds.LonMax, manifest.Bounds.LatMin, manifest.Bounds.LatMax));
    }

    /// <summary>
    /// Parse a GeoJSON FeatureCollection into <see cref="MapFeature"/>s.
    /// Handles Polygon / MultiPolygon (outline, lakes) and LineString /
    /// MultiLineString (roads, rivers). The <c>layer</c> comes from
    /// <c>properties.layer</c>; features without one use
    /// <paramref name="layerFallback"/> (the outline file has none).
    /// </summary>
    private async Task<IReadOnlyList<MapFeature>> LoadGeoJsonAsync(string url, string? layerFallback)
    {
        using var doc = JsonDocument.Parse(await _http.GetStringAsync(url));
        var root = doc.RootElement;

        var features = new List<MapFeature>();
        if (!root.TryGetProperty("features", out var featureArray))
        {
            return features;
        }

        foreach (var feature in featureArray.EnumerateArray())
        {
            string layer = layerFallback ?? "unknown";
            string? name = null;
            if (feature.TryGetProperty("properties", out var props))
            {
                if (props.TryGetProperty("layer", out var layerEl)
                    && layerEl.ValueKind == JsonValueKind.String)
                {
                    layer = layerEl.GetString()!;
                }

                if (props.TryGetProperty("name", out var nameEl)
                    && nameEl.ValueKind == JsonValueKind.String)
                {
                    name = nameEl.GetString();
                }
            }

            if (!feature.TryGetProperty("geometry", out var geometry)
                || geometry.ValueKind == JsonValueKind.Null)
            {
                continue;
            }

            string? type = geometry.TryGetProperty("type", out var typeEl)
                ? typeEl.GetString()
                : null;
            if (type is null || !geometry.TryGetProperty("coordinates", out var coords))
            {
                continue;
            }

            var parts = type switch
            {
                // Polygon: coordinates = [ ring, ring, ... ], ring = [ [lon, lat], ... ]
                "Polygon" => ReadRings(coords),
                // MultiPolygon: coordinates = [ polygon, ... ], polygon = [ ring, ... ]
                "MultiPolygon" => coords.EnumerateArray().SelectMany(ReadRings).ToList(),
                // LineString: coordinates = [ [lon, lat], ... ]
                "LineString" => new List<IReadOnlyList<(double Lon, double Lat)>> { ReadPoints(coords) },
                // MultiLineString: coordinates = [ line, ... ]
                "MultiLineString" => coords.EnumerateArray().Select(ReadPoints).ToList(),
                _ => new List<IReadOnlyList<(double Lon, double Lat)>>()
            };

            if (parts.Count == 0)
            {
                continue;
            }

            string kind = type is "Polygon" or "MultiPolygon" ? "Polygon" : "Line";
            features.Add(new MapFeature(kind, layer, name, parts));
        }

        return features;
    }

    private static List<IReadOnlyList<(double Lon, double Lat)>> ReadRings(JsonElement rings)
    {
        var result = new List<IReadOnlyList<(double Lon, double Lat)>>();
        foreach (var ring in rings.EnumerateArray())
        {
            result.Add(ReadPoints(ring));
        }

        return result;
    }

    private static IReadOnlyList<(double Lon, double Lat)> ReadPoints(JsonElement points)
    {
        var result = new List<(double Lon, double Lat)>();
        foreach (var point in points.EnumerateArray())
        {
            // GeoJSON positions are [longitude, latitude].
            result.Add((point[0].GetDouble(), point[1].GetDouble()));
        }

        return result;
    }

    // --- Manifest DTOs (internal shape of state.json) ---

    public sealed record StatePackIndexEntry(string Id, string Name);

    private sealed record StateManifest(
        string Id,
        string Name,
        string Abbreviation,
        ManifestBounds Bounds,
        List<ManifestLayer> Layers,
        ManifestFiles Files);

    private sealed record ManifestBounds(double LonMin, double LonMax, double LatMin, double LatMax);

    private sealed record ManifestLayer(string Id, string Label, bool VisibleByDefault);

    private sealed record ManifestFiles(string Cities, string Outline, string Landmarks);
}

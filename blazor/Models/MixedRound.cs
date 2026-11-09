namespace OregonGeographyGame.Models;

/// <summary>
/// One round of City County Mode: either a city round (drop a pin for
/// the named city) or a county round (click the named county on the
/// boundary grid). Exactly one of <see cref="City"/> / <see cref="County"/>
/// is set; <see cref="IsCounty"/> says which.
/// </summary>
public sealed record MixedRound(City? City, MapFeature? County)
{
    public bool IsCounty => County is not null;
}

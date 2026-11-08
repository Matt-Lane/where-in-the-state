using System.Security.Cryptography;
using System.Text;
using OregonGeographyGame.Models;

namespace OregonGeographyGame.Services;

/// <summary>
/// Deterministic game selection: the same seed string always produces
/// the same cities in the same order, in any browser, at any time.
/// Algorithm (per GAME-SPEC.md §5): SHA-256 of the UTF-8 seed string,
/// first 4 bytes as an int, <see cref="Random"/> with that int, a
/// Fisher-Yates shuffle of a copy of the pool, take the first N.
/// Never use <c>string.GetHashCode()</c> here — it is not stable across
/// runtimes/runs. Never use <c>Guid</c>, <c>Random.Shared</c>, or a
/// time-based seed for game selection.
/// </summary>
public sealed class SeededGameService
{
    /// <summary>
    /// Select <paramref name="count"/> cities (default 10) from
    /// <paramref name="pool"/> for <paramref name="seed"/>, with no
    /// repeats (sampling without replacement, guaranteed by the shuffle).
    /// The input pool is not modified.
    /// </summary>
    public IReadOnlyList<City> SelectCities(IReadOnlyList<City> pool, string seed, int count = 10)
        => SelectItems(pool, seed, count);

    /// <summary>
    /// The same deterministic selection, for any pool (cities, counties, …).
    /// The same seed string always produces the same items in the same order.
    /// </summary>
    public IReadOnlyList<T> SelectItems<T>(IReadOnlyList<T> pool, string seed, int count = 10)
    {
        ArgumentNullException.ThrowIfNull(pool);
        if (string.IsNullOrWhiteSpace(seed))
        {
            throw new ArgumentException("Seed must not be empty.", nameof(seed));
        }

        if (count < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(count));
        }

        count = Math.Min(count, pool.Count);

        using var sha = SHA256.Create();
        byte[] hash = sha.ComputeHash(Encoding.UTF8.GetBytes(seed.Trim()));
        int seedInt = BitConverter.ToInt32(hash, 0);

        var rng = new Random(seedInt);
        var shuffled = pool.ToList();
        for (int i = shuffled.Count - 1; i > 0; i--)
        {
            int j = rng.Next(i + 1);
            (shuffled[i], shuffled[j]) = (shuffled[j], shuffled[i]);
        }

        return shuffled.Take(count).ToList();
    }

    /// <summary>Today's daily seed, e.g. "OR-2026-11-06" (local date).</summary>
    public string DailySeed(string abbreviation = "OR")
        => $"{abbreviation}-{DateTime.Now:yyyy-MM-dd}";

    /// <summary>
    /// A short human-friendly random seed, e.g. "OR-7K2Q9P".
    /// This is only for *generating* a seed string; game selection itself
    /// stays deterministic via <see cref="SelectCities"/>.
    /// </summary>
    public string RandomSeed(string abbreviation = "OR")
    {
        const string alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
        Span<char> chars = stackalloc char[6];
        for (int i = 0; i < chars.Length; i++)
        {
            chars[i] = alphabet[Random.Shared.Next(alphabet.Length)];
        }

        return $"{abbreviation}-{new string(chars)}";
    }
}

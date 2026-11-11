namespace OregonGeographyGame.Models;

/// <summary>Everything needed to start one game.</summary>
public sealed record GameConfig(
    string StateId,
    string Seed,            // e.g. "2026-11-06"
    int QuestionCount = 10);

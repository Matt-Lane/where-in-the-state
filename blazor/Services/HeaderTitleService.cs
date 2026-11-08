namespace OregonGeographyGame.Services;

/// <summary>
/// Holds the title shown in the site header. The game page sets it as the
/// phase changes; MainLayout renders it and refreshes when it changes.
/// </summary>
public sealed class HeaderTitleService
{
    public string Title { get; private set; } = "Where in the State";

    public event Action? TitleChanged;

    public void SetTitle(string title)
    {
        if (title == Title)
        {
            return;
        }

        Title = title;
        TitleChanged?.Invoke();
    }
}

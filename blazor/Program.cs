using Microsoft.AspNetCore.Components.Web;
using Microsoft.AspNetCore.Components.WebAssembly.Hosting;
using OregonGeographyGame;
using OregonGeographyGame.Services;

var builder = WebAssemblyHostBuilder.CreateDefault(args);
builder.RootComponents.Add<App>("#app");
builder.RootComponents.Add<HeadOutlet>("head::after");

// HttpClient pointed at the app's own base address, so the state packs
// under wwwroot/data/ can be fetched with relative URLs.
builder.Services.AddScoped(sp => new HttpClient
{
    BaseAddress = new Uri(builder.HostEnvironment.BaseAddress)
});

// Game services. SeededGameService and DistanceService are pure logic
// (no I/O), so singleton lifetime is fine; StatePackLoader does I/O
// via the scoped HttpClient above.
builder.Services.AddSingleton<SeededGameService>();
builder.Services.AddSingleton<DistanceService>();
builder.Services.AddScoped<StatePackLoader>();

await builder.Build().RunAsync();

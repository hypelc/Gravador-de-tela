using System.Text.Json;
using Microsoft.Win32;

namespace GravaTela;

internal sealed record Preferences
{
    public string OutputFolder { get; init; } = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyVideos), "GravaTela");
    public bool StartWithWindows { get; init; }
    public string? MonitorDeviceName { get; init; }
    public int FrameRate { get; init; } = 30;
    public static string DataFolder => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "GravaTela");
    public static string Sessions => Path.Combine(DataFolder, "Sessoes");
    public static Preferences Load()
    {
        try
        {
            var p = JsonSerializer.Deserialize<Preferences>(File.ReadAllText(Path.Combine(DataFolder, "settings.json")));
            return p is not null && Path.IsPathFullyQualified(p.OutputFolder) ? p : new();
        }
        catch (Exception ex) when (ex is IOException or JsonException or UnauthorizedAccessException or ArgumentException) { return new(); }
    }
    public void Save()
    {
        Directory.CreateDirectory(DataFolder);
        string path = Path.Combine(DataFolder, "settings.json"), temp = path + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(this));
        using var run = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run");
        object? old = run.GetValue("GravaTela");
        try
        {
            if (StartWithWindows) run.SetValue("GravaTela", $"\"{Environment.ProcessPath}\" --background");
            else run.DeleteValue("GravaTela", false);
            File.Move(temp, path, true);
        }
        catch
        {
            if (old is string value) run.SetValue("GravaTela", value); else run.DeleteValue("GravaTela", false);
            throw;
        }
    }
}

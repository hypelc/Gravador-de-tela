using System.Diagnostics;
using GravaTela.Core;
using Microsoft.Win32;

namespace GravaTela;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        using var mutex = new Mutex(true, @"Local\GravaTela.App.Instance", out bool first);
        if (!first)
        {
            try { using var e = EventWaitHandle.OpenExisting(@"Local\GravaTela.App.Show"); e.Set(); } catch (WaitHandleCannotBeOpenedException) { }
            return;
        }
        try { using var context = new TrayContext(args.Contains("--background")); Application.Run(context); }
        catch (Exception ex) { MessageBox.Show("Não foi possível iniciar o GravaTela.\n" + ex.Message, "GravaTela", MessageBoxButtons.OK, MessageBoxIcon.Error); }
        finally { mutex.ReleaseMutex(); }
    }
}

internal sealed class TrayContext : ApplicationContext
{
    private Preferences prefs = Preferences.Load();
    private readonly ProcessJob job = new();
    private readonly Recorder recorder;
    private readonly MainForm window;
    private readonly Hotkeys hotkeys = new();
    private readonly NotifyIcon tray;
    private readonly ContextMenuStrip menu = new();
    private readonly System.Windows.Forms.Timer timer = new() { Interval = 250 };
    private readonly EventWaitHandle show = new(false, EventResetMode.AutoReset, @"Local\GravaTela.App.Show");
    private readonly EventWaitHandle stopSignal = new(false, EventResetMode.AutoReset, @"Local\GravaTela.App.Stop");
    private bool busy, exiting, firstTick = true;
    private readonly bool background;
    private readonly ToolStripMenuItem toggleItem, saveItem, recoveryItem;
    public TrayContext(bool background)
    {
        this.background = background;
        recorder = new Recorder(new Ffmpeg(Path.Combine(AppContext.BaseDirectory, "tools", "ffmpeg.exe"), ownProcess: job.Add), Preferences.Sessions);
        window = new MainForm(() => _ = Run(Toggle), () => _ = Run(Save), prefs);
        // Create the UI handle before asynchronous callbacks and session-change events.
        _ = window.Handle;
        tray = new NotifyIcon { Icon = SystemIcons.Application, Text = "GravaTela • Pronto", Visible = true, ContextMenuStrip = menu };
        menu.Items.Add("Abrir GravaTela", null, (_, _) => Show());
        toggleItem = (ToolStripMenuItem)menu.Items.Add("Gravar / pausar / retomar   Ctrl+Shift+F9", null, (_, _) => _ = Run(Toggle));
        saveItem = (ToolStripMenuItem)menu.Items.Add("Parar e salvar   Ctrl+Shift+F10", null, (_, _) => _ = Run(Save));
        menu.Items.Add("Abrir pasta de vídeos", null, (_, _) => OpenFolder(prefs.OutputFolder));
        recoveryItem = (ToolStripMenuItem)menu.Items.Add("Recuperar gravação interrompida…", null, (_, _) => _ = Run(Recover));
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Sair", null, (_, _) => _ = Run(ExitSafely));
        hotkeys.Pressed += id => _ = Run(id == 1 ? Toggle : Save);
        tray.DoubleClick += (_, _) => Show();
        window.ChooseFolder = () =>
        {
            using var picker = new FolderBrowserDialog { Description = "Pasta para salvar as gravações", InitialDirectory = prefs.OutputFolder, UseDescriptionForTitle = true };
            if (picker.ShowDialog(window) == DialogResult.OK) ChangePreferences(prefs with { OutputFolder = picker.SelectedPath });
        };
        window.OpenFolder = () => OpenFolder(prefs.OutputFolder);
        window.ChangeStartup = value => ChangePreferences(prefs with { StartWithWindows = value });
        window.ChangeCapture = (monitor, fps) => ChangePreferences(prefs with { MonitorDeviceName = monitor, FrameRate = fps });
        recorder.Changed += Refresh;
        timer.Tick += async (_, _) =>
        {
            if (exiting) return;
            if (firstTick)
            {
                firstTick = false;
                if (!background) Show();
                if (!hotkeys.ToggleAvailable || !hotkeys.StopAvailable)
                {
                    Show();
                    MessageBox.Show(window, "Um atalho já está em uso por outro programa.\n" + (!hotkeys.ToggleAvailable ? "Ctrl + Shift + F9 está indisponível.\n" : "") + (!hotkeys.StopAvailable ? "Ctrl + Shift + F10 está indisponível.\n" : "") + "Os botões continuam funcionando. Feche o programa que usa o atalho e reabra o GravaTela.", "Atalho ocupado");
                }
                if (PendingSessions().Length > 0) window.Notice("Há gravação interrompida. Use Recuperar no menu da bandeja.");
            }
            if (show.WaitOne(0)) Show();
            if (!busy && stopSignal.WaitOne(0)) { await Run(ExitSafely); return; }
            if (!busy && recorder.State == RecordingState.Recording && !recorder.EncoderRunning)
            {
                await Run(async () => { await recorder.ToggleAsync(Area()); });
                return;
            }
            Refresh();
        };
        SystemEvents.SessionSwitch += OnSession;
        SystemEvents.PowerModeChanged += OnPower;
        timer.Start(); Refresh();
    }
    private CaptureSettings Area()
    {
        var screen = Screen.AllScreens.FirstOrDefault(s => s.DeviceName == prefs.MonitorDeviceName)
            ?? Screen.PrimaryScreen ?? Screen.AllScreens[0];
        var r = screen.Bounds;
        return new(r.X, r.Y, r.Width, r.Height, prefs.FrameRate);
    }
    private async Task Run(Func<Task> action)
    {
        if (busy || exiting) return;
        busy = true; Refresh();
        try { await action(); }
        catch (Exception ex)
        {
            if (exiting) return;
            Show();
            window.Notice("Não foi possível concluir. Os trechos existentes foram mantidos.");
            MessageBox.Show(window, ex.Message + (recorder.SessionFolder is { } path ? "\n\nTrechos preservados em:\n" + path : ""), "GravaTela", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        finally { busy = false; if (!exiting) Refresh(); }
    }
    private async Task Toggle()
    {
        if (recorder.State is RecordingState.Idle or RecordingState.Paused)
        {
            Directory.CreateDirectory(prefs.OutputFolder);
            // Test destination access before a long recording, without replacing any file.
            var probe = Path.Combine(prefs.OutputFolder, ".GravaTela-" + Guid.NewGuid().ToString("N"));
            using (File.Create(probe)) { }
            File.Delete(probe);
            window.Hide(); menu.Close();
            await Task.Delay(350);
        }
        await recorder.ToggleAsync(Area());
    }
    private async Task Save()
    {
        string? path = await recorder.SaveAsync(prefs.OutputFolder);
        if (path is null) return;
        window.Notice("Salvo: " + Path.GetFileName(path));
        Show();
        tray.ShowBalloonTip(2500, "Vídeo salvo", Path.GetFileName(path), ToolTipIcon.Info);
    }
    private string[] PendingSessions() => Directory.Exists(Preferences.Sessions)
        ? Directory.GetDirectories(Preferences.Sessions).Where(p => Directory.GetFiles(p, "segment-*.mkv").Length > 0).Order().ToArray() : [];
    private async Task Recover()
    {
        if (recorder.State == RecordingState.NeedsRecovery) recorder.PreserveAndReset();
        if (recorder.State != RecordingState.Idle) return;
        var sessions = PendingSessions();
        if (sessions.Length == 0) { Show(); window.Notice("Não há gravações para recuperar."); return; }
        using var dialog = new Form { Text = "Recuperar gravação", ClientSize = new Size(450, 250), StartPosition = FormStartPosition.CenterParent, Font = window.Font, MinimizeBox = false, MaximizeBox = false };
        var list = new ListBox { Dock = DockStyle.Fill };
        foreach (var session in sessions) list.Items.Add(Path.GetFileName(session));
        list.SelectedIndex = 0;
        var button = new Button { Text = "Recuperar e salvar MP4", Dock = DockStyle.Bottom, Height = 40, DialogResult = DialogResult.OK };
        dialog.Controls.Add(list); dialog.Controls.Add(button); dialog.AcceptButton = button;
        Show();
        if (dialog.ShowDialog(window) != DialogResult.OK) return;
        string? path = await recorder.RecoverAsync(sessions[list.SelectedIndex], prefs.OutputFolder);
        window.Notice("Recuperado: " + Path.GetFileName(path));
    }
    private async Task ExitSafely()
    {
        if (recorder.State is not (RecordingState.Idle or RecordingState.NeedsRecovery)) await recorder.SaveAsync(prefs.OutputFolder);
        exiting = true; window.AllowClose = true; window.Close(); ExitThread();
    }
    private void Refresh()
    {
        window.RefreshState(recorder, busy);
        tray.Text = (recorder.State switch { RecordingState.Recording => "GravaTela • Gravando", RecordingState.Paused => "GravaTela • Pausado", RecordingState.Saving => "GravaTela • Salvando", _ => "GravaTela" });
        tray.Icon = recorder.State == RecordingState.Recording ? SystemIcons.Warning : SystemIcons.Application;
        toggleItem.Enabled = !busy && recorder.State is RecordingState.Idle or RecordingState.Recording or RecordingState.Paused;
        saveItem.Enabled = !busy && recorder.State is RecordingState.Recording or RecordingState.Paused or RecordingState.NeedsRecovery;
        recoveryItem.Enabled = !busy && recorder.State is RecordingState.Idle or RecordingState.NeedsRecovery;
    }
    private void Show() { window.Show(); window.WindowState = FormWindowState.Normal; window.Activate(); }
    private void ChangePreferences(Preferences next)
    {
        try { next.Save(); prefs = next; window.SetFolder(next.OutputFolder); }
        catch (Exception ex) { MessageBox.Show(window, "Não foi possível salvar a preferência: " + ex.Message, "GravaTela"); }
    }
    private void OpenFolder(string path)
    {
        try { Directory.CreateDirectory(path); Process.Start(new ProcessStartInfo(path) { UseShellExecute = true }); }
        catch (Exception ex) { MessageBox.Show(window, ex.Message, "GravaTela"); }
    }
    private void PauseForSystem()
    {
        if (exiting || window.IsDisposed) return;
        window.BeginInvoke(new Action(() =>
        {
            if (recorder.State == RecordingState.Recording) _ = Run(async () => await recorder.ToggleAsync(Area()));
        }));
    }
    private void OnSession(object? sender, SessionSwitchEventArgs e) { if (e.Reason == SessionSwitchReason.SessionLock) PauseForSystem(); }
    private void OnPower(object? sender, PowerModeChangedEventArgs e) { if (e.Mode == PowerModes.Suspend) PauseForSystem(); }
    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            exiting = true; SystemEvents.SessionSwitch -= OnSession; SystemEvents.PowerModeChanged -= OnPower;
            timer.Dispose(); hotkeys.Dispose(); tray.Visible = false; tray.Dispose(); menu.Dispose(); job.Dispose();
            show.Dispose(); stopSignal.Dispose(); window.Dispose();
        }
        base.Dispose(disposing);
    }
}

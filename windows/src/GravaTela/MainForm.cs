using GravaTela.Core;

namespace GravaTela;

internal sealed class MainForm : Form
{
    private readonly Label state = new() { AutoSize = true, Text = "Pronto para gravar" };
    private readonly Label clock = new() { AutoSize = true, Text = "00:00:00", Font = new Font("Segoe UI", 28, FontStyle.Bold) };
    private readonly Button record = new() { Text = "●  Gravar", AutoSize = true };
    private readonly Button pause = new() { Text = "Pausar", AutoSize = true };
    private readonly Button stop = new() { Text = "■  Parar e salvar", AutoSize = true };
    private readonly Label folder = new() { AutoEllipsis = true, Dock = DockStyle.Fill };
    private readonly Button choose = new() { Text = "Escolher pasta…", AutoSize = true };
    private readonly ComboBox monitors = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 300 };
    private readonly ComboBox frameRates = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 105 };
    private readonly Screen[] screens = Screen.AllScreens;
    private readonly CheckBox startup = new() { Text = "Iniciar com o Windows", AutoSize = true };
    private readonly Label result = new() { AutoSize = true, MaximumSize = new Size(510, 0) };
    private readonly Action toggleAction, stopAction;
    public bool AllowClose;
    public Action? ChooseFolder, OpenFolder;
    public Action<bool>? ChangeStartup;
    public Action<string, int>? ChangeCapture;
    public MainForm(Action toggle, Action finish, Preferences prefs)
    {
        toggleAction = toggle; stopAction = finish;
        Text = "GravaTela"; ClientSize = new Size(570, 510); MinimumSize = new Size(590, 550);
        StartPosition = FormStartPosition.CenterScreen; Font = new Font("Segoe UI", 10); AutoScaleMode = AutoScaleMode.Dpi;
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(24), ColumnCount = 1, RowCount = 10 };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        foreach (int h in new[] { 34, 26, 65, 52, 53, 60, 32, 35, 28 }) layout.RowStyles.Add(new RowStyle(SizeType.Absolute, h));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.Controls.Add(new Label { Text = "GravaTela", Font = new Font("Segoe UI", 18, FontStyle.Bold), AutoSize = true }, 0, 0);
        layout.Controls.Add(state, 0, 1); layout.Controls.Add(clock, 0, 2);
        var buttons = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = false };
        foreach (var b in new[] { record, pause, stop }) { b.MinimumSize = new Size(145, 36); buttons.Controls.Add(b); }
        layout.Controls.Add(buttons, 0, 3);
        layout.Controls.Add(new Label { Text = "Ctrl + Shift + F9  →  Gravar / pausar / retomar\nCtrl + Shift + F10  →  Parar e salvar", AutoSize = true }, 0, 4);
        var captureOptions = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = false };
        for (int i = 0; i < screens.Length; i++)
        {
            var screen = screens[i];
            monitors.Items.Add($"Tela {i + 1}{(screen.Primary ? " (principal)" : "")} — {screen.Bounds.Width}×{screen.Bounds.Height}");
        }
        int savedScreen = Array.FindIndex(screens, s => s.DeviceName == prefs.MonitorDeviceName);
        monitors.SelectedIndex = savedScreen >= 0 ? savedScreen : Array.FindIndex(screens, s => s.Primary);
        frameRates.Items.AddRange(["30 FPS", "60 FPS"]);
        frameRates.SelectedIndex = prefs.FrameRate == 60 ? 1 : 0;
        captureOptions.Controls.Add(new Label { Text = "Monitor", AutoSize = true, Margin = new Padding(0, 8, 6, 0) });
        captureOptions.Controls.Add(monitors);
        captureOptions.Controls.Add(new Label { Text = "FPS", AutoSize = true, Margin = new Padding(12, 8, 6, 0) });
        captureOptions.Controls.Add(frameRates);
        layout.Controls.Add(captureOptions, 0, 5);
        layout.Controls.Add(folder, 0, 6);
        var paths = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = false };
        var open = new Button { Text = "Abrir pasta", AutoSize = true };
        paths.Controls.AddRange([choose, open]); layout.Controls.Add(paths, 0, 7);
        startup.Checked = prefs.StartWithWindows; layout.Controls.Add(startup, 0, 8);
        layout.Controls.Add(result, 0, 9); Controls.Add(layout);
        record.Click += (_, _) => toggleAction(); pause.Click += (_, _) => toggleAction(); stop.Click += (_, _) => stopAction();
        choose.Click += (_, _) => ChooseFolder?.Invoke(); open.Click += (_, _) => OpenFolder?.Invoke();
        startup.CheckedChanged += (_, _) => ChangeStartup?.Invoke(startup.Checked);
        void CaptureChanged()
        {
            if (monitors.SelectedIndex >= 0 && frameRates.SelectedIndex >= 0)
                ChangeCapture?.Invoke(screens[monitors.SelectedIndex].DeviceName, frameRates.SelectedIndex == 1 ? 60 : 30);
        }
        monitors.SelectedIndexChanged += (_, _) => CaptureChanged();
        frameRates.SelectedIndexChanged += (_, _) => CaptureChanged();
        FormClosing += (_, e) =>
        {
            if (!AllowClose && e.CloseReason == CloseReason.UserClosing) { e.Cancel = true; Hide(); }
        };
        SetFolder(prefs.OutputFolder);
    }
    public void SetFolder(string value) => folder.Text = "Salvar em: " + value;
    public void Notice(string value) => result.Text = value;
    public void RefreshState(Recorder recorder, bool transition)
    {
        var s = recorder.State;
        state.Text = s switch
        {
            RecordingState.Idle => "Pronto para gravar • Sem áudio • MP4",
            RecordingState.Starting => "Iniciando captura…",
            RecordingState.Recording => "● Gravando a tela selecionada",
            RecordingState.Pausing => "Finalizando trecho…",
            RecordingState.Paused => "Ⅱ Pausado — esse intervalo não entra no vídeo",
            RecordingState.Saving => "Salvando MP4…",
            _ => "Gravação interrompida — tente parar e salvar"
        };
        state.ForeColor = s == RecordingState.Recording ? Color.Firebrick : SystemColors.ControlText;
        clock.Text = $"{(int)recorder.Duration.TotalHours:00}:{recorder.Duration.Minutes:00}:{recorder.Duration.Seconds:00}";
        record.Enabled = !transition && s == RecordingState.Idle;
        pause.Enabled = !transition && s is RecordingState.Recording or RecordingState.Paused;
        pause.Text = s == RecordingState.Paused ? "Retomar" : "Pausar";
        stop.Enabled = !transition && s is RecordingState.Recording or RecordingState.Paused or RecordingState.NeedsRecovery;
        choose.Enabled = !transition && s is RecordingState.Idle or RecordingState.NeedsRecovery;
        monitors.Enabled = !transition && s == RecordingState.Idle;
        frameRates.Enabled = !transition && s == RecordingState.Idle;
    }
}

namespace GravaTela.Core;

public enum RecordingState { Idle, Starting, Recording, Pausing, Paused, Saving, NeedsRecovery }

public sealed class Recorder(Ffmpeg encoder, string sessionsRoot)
{
    private readonly SemaphoreSlim gate = new(1, 1);
    private int segment;
    private TimeSpan completed;
    private CaptureSettings? originalCapture;
    public RecordingState State { get; private set; }
    public string? SessionFolder { get; private set; }
    public string? LastSaved { get; private set; }
    public bool EncoderRunning => encoder.IsRunning;
    public TimeSpan Duration => completed + (State == RecordingState.Recording ? encoder.SegmentTime : TimeSpan.Zero);
    public event Action? Changed;
    private void Set(RecordingState state) { State = state; Changed?.Invoke(); }
    public async Task ToggleAsync(CaptureSettings capture)
    {
        if (!await gate.WaitAsync(0)) return;
        try
        {
            if (State == RecordingState.Recording)
            {
                Set(RecordingState.Pausing);
                try { completed += await encoder.StopAsync(); Set(RecordingState.Paused); }
                catch { Set(RecordingState.NeedsRecovery); throw; }
                return;
            }
            if (State is not (RecordingState.Idle or RecordingState.Paused)) return;
            bool fresh = State == RecordingState.Idle;
            if (fresh)
            {
                originalCapture = capture; segment = 0; completed = TimeSpan.Zero;
                SessionFolder = Path.Combine(sessionsRoot, DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N")[..8]);
                Directory.CreateDirectory(SessionFolder);
            }
            else if (capture != originalCapture) throw new IOException("A tela ou o FPS mudou. Pare e salve esta gravação antes de iniciar outra.");
            Set(RecordingState.Starting);
            string path = Path.Combine(SessionFolder!, $"segment-{segment++:D6}.mkv");
            try { await encoder.StartAsync(path, capture); Set(RecordingState.Recording); }
            catch
            {
                // Keep even an incomplete fragment; it may contain recoverable footage.
                Set(RecordingState.NeedsRecovery); throw;
            }
        }
        finally { gate.Release(); }
    }
    public async Task<string?> SaveAsync(string folder)
    {
        if (!await gate.WaitAsync(0)) return null;
        try
        {
            if (State == RecordingState.Idle) return null;
            if (State is RecordingState.Recording or RecordingState.NeedsRecovery)
            {
                Set(RecordingState.Pausing);
                try { completed += await encoder.StopAsync(); }
                catch { Set(RecordingState.NeedsRecovery); throw; }
            }
            Set(RecordingState.Saving);
            try
            {
                string output = Path.Combine(folder, $"GravaTela-{DateTime.Now:yyyyMMdd-HHmmss}-{Guid.NewGuid().ToString("N")[..6]}.mp4");
                await encoder.MergeAsync(SessionFolder!, output);
                LastSaved = output;
                TryClean(SessionFolder!); SessionFolder = null;
                Set(RecordingState.Idle);
                return output;
            }
            catch { Set(RecordingState.NeedsRecovery); throw; }
        }
        finally { gate.Release(); }
    }
    public async Task<string?> RecoverAsync(string session, string folder)
    {
        if (!await gate.WaitAsync(0)) return null;
        try
        {
            if (State != RecordingState.Idle) throw new InvalidOperationException("Finalize a gravação atual antes de recuperar outra.");
            Set(RecordingState.Saving);
            try
            {
                string output = Path.Combine(folder, $"GravaTela-recuperado-{Guid.NewGuid():N}.mp4");
                await encoder.MergeAsync(session, output);
                LastSaved = output; TryClean(session);
                return output;
            }
            finally { Set(RecordingState.Idle); }
        }
        finally { gate.Release(); }
    }
    public void PreserveAndReset()
    {
        if (State != RecordingState.NeedsRecovery || encoder.IsRunning) throw new InvalidOperationException("Pare a captura antes de continuar.");
        SessionFolder = null; completed = TimeSpan.Zero; Set(RecordingState.Idle);
    }
    private static void TryClean(string session)
    {
        try { Directory.Delete(session, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
    }
}

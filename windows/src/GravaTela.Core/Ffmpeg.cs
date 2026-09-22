using System.Diagnostics;
using System.Globalization;
using System.Text;

namespace GravaTela.Core;

public sealed record CaptureSettings(int X, int Y, int Width, int Height, int FrameRate = 30);

public sealed class Ffmpeg(string executable, bool testSource = false, Action<Process>? ownProcess = null, string videoEncoder = "libx264")
{
    private Process? process;
    private Task? stderrTask, progressTask;
    private readonly StringBuilder errors = new();
    private long elapsedTicks;
    public TimeSpan SegmentTime => TimeSpan.FromTicks(Interlocked.Read(ref elapsedTicks));
    public bool IsRunning => process is { HasExited: false };
    public string ErrorText { get { lock (errors) return errors.ToString(); } }
    private Process Create(IEnumerable<string> args)
    {
        var info = new ProcessStartInfo(executable) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true, RedirectStandardError = true, RedirectStandardOutput = true };
        foreach (var arg in args) info.ArgumentList.Add(arg);
        return new Process { StartInfo = info };
    }
    public async Task StartAsync(string path, CaptureSettings capture)
    {
        if (process is not null) throw new InvalidOperationException("Já existe uma captura em andamento.");
        if (capture.FrameRate is not (30 or 60) || capture.Width <= 0 || capture.Height <= 0)
            throw new ArgumentOutOfRangeException(nameof(capture), "Escolha 30 ou 60 FPS e uma tela válida.");
        lock (errors) errors.Clear();
        Interlocked.Exchange(ref elapsedTicks, 0);
        List<string> args = ["-hide_banner", "-loglevel", "warning", "-y", "-stats_period", "0.2", "-progress", "pipe:1"];
        string fps = capture.FrameRate.ToString(CultureInfo.InvariantCulture);
        if (testSource) args.AddRange(["-re", "-f", "lavfi", "-i", $"testsrc2=size={capture.Width}x{capture.Height}:rate={fps}"]);
        else args.AddRange(["-f", "gdigrab", "-framerate", fps, "-draw_mouse", "1", "-offset_x", capture.X.ToString(CultureInfo.InvariantCulture), "-offset_y", capture.Y.ToString(CultureInfo.InvariantCulture), "-video_size", $"{capture.Width}x{capture.Height}", "-i", "desktop"]);
        args.AddRange(["-an", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", videoEncoder]);
        if (videoEncoder == "libx264") args.AddRange(["-preset", "ultrafast", "-tune", "zerolatency", "-crf", "23"]);
        args.AddRange(["-pix_fmt", "yuv420p", "-g", (capture.FrameRate * 2).ToString(CultureInfo.InvariantCulture), "-fps_mode", "cfr", "-f", "matroska", path]);
        var p = Create(args);
        var ready = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        try
        {
            if (!p.Start()) throw new IOException("Não foi possível iniciar o gravador.");
            process = p;
            ownProcess?.Invoke(p);
            stderrTask = Task.Run(async () =>
            {
                while (await p.StandardError.ReadLineAsync() is { } line)
                {
                    lock (errors) { errors.AppendLine(line); if (errors.Length > 12000) errors.Remove(0, errors.Length - 12000); }
                }
            });
            progressTask = Task.Run(async () =>
            {
                while (await p.StandardOutput.ReadLineAsync() is { } line)
                {
                    if (line.StartsWith("frame=") && long.TryParse(line.AsSpan(6), out long frame) && frame > 0) ready.TrySetResult();
                    if (line.StartsWith("out_time_us=") && long.TryParse(line.AsSpan(12), out long micros) && micros >= 0) Interlocked.Exchange(ref elapsedTicks, micros * 10);
                }
                if (!ready.Task.IsCompleted) ready.TrySetException(new IOException("A captura não iniciou. " + ErrorText));
            });
            await ready.Task.WaitAsync(TimeSpan.FromSeconds(20));
            if (p.HasExited) throw new IOException("A captura foi interrompida. " + ErrorText);
        }
        catch
        {
            if (process is not null) await AbortAsync(); else p.Dispose();
            throw;
        }
    }
    public async Task<TimeSpan> StopAsync()
    {
        var p = process;
        if (p is null) return SegmentTime;
        try
        {
            if (!p.HasExited)
            {
                try { await p.StandardInput.WriteLineAsync("q"); await p.StandardInput.FlushAsync(); }
                catch (IOException) when (p.HasExited) { }
            }
            try { await p.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(30)); }
            catch (TimeoutException) { p.Kill(true); await p.WaitForExitAsync(); throw new IOException("O gravador demorou demais para parar. Os trechos foram preservados para recuperação."); }
            if (stderrTask is not null) await stderrTask;
            if (progressTask is not null) await progressTask;
            if (p.ExitCode != 0) throw new IOException("A gravação foi interrompida. " + ErrorText);
            return SegmentTime;
        }
        finally { p.Dispose(); process = null; }
    }
    public async Task AbortAsync()
    {
        if (process is not { } p) return;
        try { if (!p.HasExited) p.Kill(true); await p.WaitForExitAsync(); if (stderrTask is not null) await stderrTask; if (progressTask is not null) await progressTask; }
        finally { p.Dispose(); process = null; }
    }
    public async Task MergeAsync(string session, string output)
    {
        var segments = Directory.GetFiles(session, "segment-*.mkv").Where(p => new FileInfo(p).Length >= 1024).Order(StringComparer.Ordinal).ToArray();
        if (segments.Length == 0) throw new IOException("Não há trechos de gravação para salvar.");
        // Names are generated by the app; the concat file contains no user-supplied paths.
        string list = Path.Combine(session, "concat.txt");
        await File.WriteAllLinesAsync(list, segments.Select(p => $"file '{Path.GetFileName(p)}'"), new UTF8Encoding(false));
        Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        string temporary = Path.Combine(Path.GetDirectoryName(output)!, ".GravaTela-" + Guid.NewGuid().ToString("N") + ".mp4");
        try
        {
            using var p = Create(["-hide_banner", "-loglevel", "error", "-nostdin", "-f", "concat", "-safe", "1", "-i", list, "-map", "0:v:0", "-c", "copy", "-movflags", "+faststart", "-f", "mp4", temporary]);
            if (!p.Start()) throw new IOException("Não foi possível salvar o vídeo.");
            ownProcess?.Invoke(p);
            var err = p.StandardError.ReadToEndAsync();
            var stdout = p.StandardOutput.ReadToEndAsync();
            // Concat copies encoded packets. Large files can take time; do not truncate them with a short timeout.
            await p.WaitForExitAsync();
            string details = await err; await stdout;
            if (p.ExitCode != 0 || !File.Exists(temporary) || new FileInfo(temporary).Length < 1024) throw new IOException("Falha ao salvar o MP4. " + details);
            File.Move(temporary, output, false);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
}

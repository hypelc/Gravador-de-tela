using System.Diagnostics;
using System.Globalization;
using GravaTela.Core;

if (args.Length is not (3 or 4)) throw new ArgumentException("Uso: testes <ffmpeg> <ffprobe> <pasta-temporaria> [encoder]");
var ffmpeg = Path.GetFullPath(args[0]); var ffprobe = Path.GetFullPath(args[1]);
var root = Path.Combine(Path.GetFullPath(args[2]), Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
void Check(bool condition, string message) { if (!condition) throw new Exception(message); Console.WriteLine("OK: " + message); }
async Task<double> Duration(string file)
{
    var info = new ProcessStartInfo(ffprobe) { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false };
    foreach (var a in new[] { "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file }) info.ArgumentList.Add(a);
    using var p = Process.Start(info)!; var output = await p.StandardOutput.ReadToEndAsync(); var err = await p.StandardError.ReadToEndAsync(); await p.WaitForExitAsync();
    if (p.ExitCode != 0) throw new Exception(err);
    return double.Parse(output.Trim(), CultureInfo.InvariantCulture);
}
async Task Decode(string file)
{
    var info = new ProcessStartInfo(ffmpeg) { RedirectStandardError = true, UseShellExecute = false };
    foreach (var a in new[] { "-v", "error", "-i", file, "-f", "null", "-" }) info.ArgumentList.Add(a);
    using var p = Process.Start(info)!; var err = await p.StandardError.ReadToEndAsync(); await p.WaitForExitAsync();
    Check(p.ExitCode == 0 && string.IsNullOrWhiteSpace(err), "MP4 inteiro decodifica sem erros");
}
async Task<string> FrameRate(string file)
{
    var info = new ProcessStartInfo(ffprobe) { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false };
    foreach (var a in new[] { "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "default=noprint_wrappers=1:nokey=1", file }) info.ArgumentList.Add(a);
    using var p = Process.Start(info)!;
    string output = await p.StandardOutput.ReadToEndAsync();
    string error = await p.StandardError.ReadToEndAsync();
    await p.WaitForExitAsync();
    if (p.ExitCode != 0) throw new Exception(error);
    return output.Trim();
}
var area = new CaptureSettings(0, 0, 320, 240);
string videoEncoder = args.Length == 4 ? args[3] : "libx264";
var r = new Recorder(new Ffmpeg(ffmpeg, testSource: true, videoEncoder: videoEncoder), Path.Combine(root, "sessions"));
Check(await r.SaveAsync(root) is null, "Parar sem gravação não cria arquivo");
var start = r.ToggleAsync(area); var duplicate = r.ToggleAsync(area); await Task.WhenAll(start, duplicate);
Check(r.State == RecordingState.Recording, "Atalhos simultâneos não enfileiram pausa acidental");
await Task.Delay(1300); await r.ToggleAsync(area);
Check(r.State == RecordingState.Paused && !r.EncoderRunning, "Pausar encerra a captura");
var session = r.SessionFolder!;
var firstDuration = await Duration(Directory.GetFiles(session, "*.mkv").Single());
var pausedDuration = r.Duration;
await Task.Delay(1600);
Check(r.Duration == pausedDuration, "Cronômetro não avança durante pausa");
try { await r.ToggleAsync(area with { Width = 640 }); throw new Exception("Mudança de resolução aceita indevidamente"); }
catch (IOException) { Check(r.State == RecordingState.Paused, "Mudança de monitor/resolução mantém sessão pausada"); }
try { await r.ToggleAsync(area with { FrameRate = 60 }); throw new Exception("Mudança de FPS aceita indevidamente"); }
catch (IOException) { Check(r.State == RecordingState.Paused, "Mudança de FPS mantém sessão pausada"); }
await r.ToggleAsync(area); await Task.Delay(1100); await r.ToggleAsync(area);
var segments = Directory.GetFiles(session, "*.mkv").Order().ToArray();
double expected = 0; foreach (var part in segments) expected += await Duration(part);
string blocked = Path.Combine(root, "not-a-directory"); File.WriteAllText(blocked, "block");
try { await r.SaveAsync(blocked); throw new Exception("Salvar em destino inválido deveria falhar"); }
catch (IOException) { Check(r.State == RecordingState.NeedsRecovery && Directory.GetFiles(session, "*.mkv").Length == 2, "Falha ao salvar preserva todos os trechos"); }
string saved = (await r.SaveAsync(Path.Combine(root, "Vídeos com espaço e acentuação")))!;
Check(File.Exists(saved) && r.State == RecordingState.Idle && !Directory.Exists(session), "Repetir salvamento gera MP4 e limpa apenas a sessão salva");
double actual = await Duration(saved);
Check(Math.Abs(actual - expected) < .15, $"MP4 concatena apenas trechos ativos: {actual:F3}s / esperado {expected:F3}s");
await Decode(saved);
await r.ToggleAsync(area); await Task.Delay(500);
string single = (await r.SaveAsync(Path.Combine(root, "out")))!;
Check(File.Exists(single) && r.State == RecordingState.Idle, "Parar diretamente enquanto grava funciona");
await Decode(single);
var bad = new Recorder(new Ffmpeg(Path.Combine(root, "missing")), Path.Combine(root, "failed"));
try { await bad.ToggleAsync(area); throw new Exception("Executável ausente deveria falhar"); }
catch (System.ComponentModel.Win32Exception) { Check(bad.State == RecordingState.NeedsRecovery && !bad.EncoderRunning, "Falha ao iniciar não deixa captura ativa"); }
bad.PreserveAndReset(); Check(bad.State == RecordingState.Idle, "Nova sessão permitida mantendo fragmentos anteriores");
var recovery = Path.Combine(root, "recovery"); Directory.CreateDirectory(recovery);
// Reuse a valid encoded file as an interrupted-session fixture; concat probes its content.
File.Copy(single, Path.Combine(recovery, "segment-000000.mkv"));
File.WriteAllBytes(Path.Combine(recovery, "segment-000001.mkv"), []);
string recovered = (await r.RecoverAsync(recovery, Path.Combine(root, "out")))!;
Check(File.Exists(recovered) && !Directory.Exists(recovery), "Recuperação salva trecho válido e ignora arquivo vazio");
await Decode(recovered);
var fast = new Recorder(new Ffmpeg(ffmpeg, testSource: true, videoEncoder: videoEncoder), Path.Combine(root, "sessions-60"));
await fast.ToggleAsync(area with { FrameRate = 60 });
await Task.Delay(700);
string at60 = (await fast.SaveAsync(Path.Combine(root, "out")))!;
Check(await FrameRate(at60) == "60/1", "60 FPS é preservado no MP4");
await Decode(at60);
Console.WriteLine("Todos os testes passaram. Arquivos de teste: " + root);

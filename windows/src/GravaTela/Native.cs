using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace GravaTela;

internal sealed class Hotkeys : NativeWindow, IDisposable
{
    [DllImport("user32.dll", SetLastError = true)] private static extern bool RegisterHotKey(IntPtr hwnd, int id, uint modifiers, uint key);
    [DllImport("user32.dll")] private static extern bool UnregisterHotKey(IntPtr hwnd, int id);
    public bool ToggleAvailable { get; }
    public bool StopAvailable { get; }
    public event Action<int>? Pressed;
    public Hotkeys()
    {
        CreateHandle(new CreateParams { Caption = "GravaTela.Hotkeys", Parent = new IntPtr(-3) });
        ToggleAvailable = RegisterHotKey(Handle, 1, 0x4006, (uint)Keys.F9);
        StopAvailable = RegisterHotKey(Handle, 2, 0x4006, (uint)Keys.F10);
    }
    protected override void WndProc(ref Message m) { if (m.Msg == 0x0312) Pressed?.Invoke(m.WParam.ToInt32()); base.WndProc(ref m); }
    public void Dispose() { UnregisterHotKey(Handle, 1); UnregisterHotKey(Handle, 2); DestroyHandle(); }
}

internal sealed class ProcessJob : IDisposable
{
    [StructLayout(LayoutKind.Sequential)] private struct BasicLimits
    {
        public long ProcessTime, JobTime;
        public uint Flags;
        public UIntPtr MinimumWorkingSet, MaximumWorkingSet;
        public uint ActiveProcesses;
        public UIntPtr Affinity;
        public uint Priority, Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] private struct IoCounters { public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes; }
    [StructLayout(LayoutKind.Sequential)] private struct Limits
    {
        public BasicLimits Basic; public IoCounters Io;
        public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern SafeFileHandle CreateJobObject(IntPtr attributes, string? name);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool SetInformationJobObject(SafeFileHandle job, int kind, ref Limits info, uint size);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool AssignProcessToJobObject(SafeFileHandle job, IntPtr process);
    private readonly SafeFileHandle handle = CreateJobObject(IntPtr.Zero, null);
    public ProcessJob()
    {
        var limits = new Limits { Basic = new BasicLimits { Flags = 0x2000 } }; // KILL_ON_JOB_CLOSE
        if (handle.IsInvalid || !SetInformationJobObject(handle, 9, ref limits, (uint)Marshal.SizeOf<Limits>())) throw new IOException("Não foi possível preparar o controle do gravador.");
    }
    public void Add(Process process)
    {
        if (!AssignProcessToJobObject(handle, process.Handle))
        {
            try { process.Kill(true); } catch (InvalidOperationException) { }
            throw new IOException("Não foi possível vincular a captura ao aplicativo.");
        }
    }
    public void Dispose() => handle.Dispose();
}

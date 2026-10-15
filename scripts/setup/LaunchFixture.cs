// Offline test executable. Never shipped as the app; no network or trading calls.
using System;
using System.IO;
using System.Threading;

internal static class LaunchFixture
{
    static int Main()
    {
        string directory = AppDomain.CurrentDomain.BaseDirectory;
        if (File.Exists(Path.Combine(directory, "exit-early"))) return 5;
        File.WriteAllText(Path.Combine(directory, "started"), "started");
        Thread.Sleep(2500);
        File.WriteAllText(Path.Combine(directory, "finished"), "finished");
        return 0;
    }
}

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading.Tasks;

namespace NHSetup
{
    // Presentation only: never estimates unfinished work or changes InstallProgress.
    // An injectable time delta makes easing deterministic in tests.
    internal sealed class ProgressAnimation
    {
        double start, elapsed, duration;
        internal double Value { get; private set; }
        internal double Target { get; private set; }
        internal bool Active { get { return Value < Target; } }
        internal void Reset() { Value = Target = start = elapsed = duration = 0; }
        internal void MoveTo(double target)
        {
            target = Math.Max(0, Math.Min(100, target));
            if (target <= Target) return;
            start = Value; Target = target; elapsed = 0;
            duration = 800 + (Target - start) * 12; // 20 points: 1.04 s; 100 points: 2 s.
        }
        internal void Advance(double milliseconds)
        {
            if (!Active || milliseconds <= 0) return;
            elapsed = Math.Min(duration, elapsed + milliseconds);
            double t = elapsed / duration;
            double eased = t * t * (3 - 2 * t);
            Value = elapsed == duration ? Target : Math.Min(Target, start + (Target - start) * eased);
        }
    }

    // Completed work stages, not downloaded bytes or an elapsed-time estimate.
    internal sealed class InstallProgress
    {
        internal readonly List<string> Keys = new List<string> { "tools", "dependencies" };
        internal readonly List<string> Names = new List<string> { "도구 준비", "의존성 설치" };
        internal int Completed { get; private set; }
        internal bool Finished { get; private set; }
        internal int Percent { get { return Completed * 100 / Keys.Count; } }
        internal InstallProgress(bool build, bool shortcut)
        {
            if (build) { Keys.Add("build"); Names.Add("앱 만들기"); }
            if (build && shortcut) { Keys.Add("shortcut"); Names.Add("바로가기"); }
            Keys.Add("done"); Names.Add("완료 확인");
        }
        internal void Observe(string stage)
        {
            if (Finished) return;
            int index = Keys.IndexOf(stage);
            if (index >= 0) Completed = Math.Max(Completed, index);
        }
        internal void Finish(bool success)
        {
            if (Finished) return;
            if (success) Completed = Keys.Count;
            Finished = true;
        }
    }

    internal sealed class InstallOptions
    {
        public bool Build = true;
        public bool Shortcut = true;
        public bool DryRun;
        public bool CheckOnly;
        public string CancellationFile;
    }

    internal sealed class RunResult
    {
        public int ExitCode;
        public bool Started;
        public bool Completed;
        public bool Retried;
        public bool Cancelled;
        public bool Success { get { return ExitCode == 0 && Started && Completed; } }
    }

    internal static class SetupCore
    {
        // Dedicated wrapper exit codes; arbitrary error text never authorizes a retry.
        internal const int PolicyBlocked = 73;
        internal const int ManagedPolicy = 74;
        internal const string Prefix = "NHSETUP|";

        internal static string ValidateRoot(string root)
        {
            string full = Path.GetFullPath(root);
            foreach (string path in new[] { "scripts/bootstrap.ps1", "justfile", "pyproject.toml", "frontend/package.json" })
                if (!File.Exists(Path.Combine(full, path)))
                    throw new InvalidOperationException("프로젝트 파일이 없습니다: " + path + "\nZIP의 압축을 모두 푼 폴더에서 실행해 주세요.");
            return full;
        }

        internal static bool CanRetry(RunResult result)
        {
            return result.ExitCode == PolicyBlocked && !result.Started && !result.Completed;
        }

        internal static string QuotePS(string value) { return "'" + value.Replace("'", "''") + "'"; }

        internal static string ValidateWritableRoot(string root)
        {
            string full = ValidateRoot(root);
            string probe = Path.Combine(full, ".nh-setup-write-" + Guid.NewGuid().ToString("N"));
            // DeleteOnClose removes only the probe this check just created, including on failure.
            using (var stream = new FileStream(probe, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1, FileOptions.DeleteOnClose))
                stream.WriteByte(0);
            return full;
        }

        internal static string ToolSummary(string output)
        {
            var lines = new List<string>();
            foreach (string line in output.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
                if (line.StartsWith(Prefix + "tool|")) lines.Add(line.Substring((Prefix + "tool|").Length));
            return lines.Count == 0 ? "도구 상태를 확인하지 못했습니다." : string.Join(Environment.NewLine, lines);
        }

        internal static async Task LaunchApplication(string root)
        {
            string exe = Path.Combine(root, "desktop", "dist", "NH FUTURES API.exe");
            if (!File.Exists(exe)) throw new FileNotFoundException("실행 파일이 없습니다. 실행 파일 만들기로 다시 설치해 주세요.", exe);
            // No job object or lifetime binding: disposing this handle must not stop the app/server.
            using (var process = Process.Start(new ProcessStartInfo(exe) {
                WorkingDirectory = Path.GetDirectoryName(exe), UseShellExecute = true
            })) {
                if (process == null) throw new InvalidOperationException("프로그램 시작을 확인하지 못했습니다.");
                await Task.Delay(700).ConfigureAwait(false);
                if (process.HasExited) throw new InvalidOperationException("프로그램이 시작 직후 종료되었습니다 (종료 코드 " + process.ExitCode + "). 프로그램 로그를 확인해 주세요.");
            }
        }

        internal static string Wrapper(string root, InstallOptions options, bool retry)
        {
            string script = Path.Combine(root, "scripts", "bootstrap.ps1");
            // File invocation respects execution policy; do NOT read/evaluate the file's contents.
            return "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; " +
                "[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false); $OutputEncoding=[Console]::OutputEncoding; " +
                "$began=$false; try { " +
                (retry ? "if ((Get-ExecutionPolicy -Scope MachinePolicy) -ne 'Undefined' -or (Get-ExecutionPolicy -Scope UserPolicy) -ne 'Undefined') { Write-Output 'NHSETUP|managed|Organization policy prevents automatic retry'; exit 74 }; " : "") +
                "& " + QuotePS(script) + " -NonInteractive" +
                (options.Build ? "" : " -SkipBuild") +
                (options.Shortcut ? "" : " -NoShortcut") +
                (options.DryRun ? " -DryRun" : "") +
                (options.CheckOnly ? " -CheckOnly" : "") +
                (options.CancellationFile == null ? "" : " -CancellationFile " + QuotePS(options.CancellationFile)) +
                " 6>&1 | ForEach-Object { if ($_ -is [string] -and $_.StartsWith('NHSETUP|begin|')) { $began=$true }; Write-Output ([string]$_) }; exit 0 " +
                "} catch { if ($_.Exception -is [System.OperationCanceledException]) { Write-Output 'NHSETUP|cancelled|Installation cancelled at a safe boundary'; exit 75 }; " +
                "if (-not $began -and $_.Exception -is [System.Management.Automation.PSSecurityException] " +
                "-and $_.FullyQualifiedErrorId -eq 'UnauthorizedAccess') { Write-Output 'NHSETUP|policy|Script execution policy blocked startup'; exit 73 }; " +
                "[Console]::Error.WriteLine($_.Exception.Message); exit 1 }";
        }

        internal static RunResult RunOnce(string root, InstallOptions options, bool retry, Action<string> output)
        {
            var result = new RunResult();
            string windows = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
            var start = new ProcessStartInfo {
                FileName = Path.Combine(windows, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
                Arguments = "-NoLogo -NoProfile -NonInteractive -OutputFormat Text " + (retry ? "-ExecutionPolicy Bypass " : "") +
                    "-EncodedCommand " + Convert.ToBase64String(Encoding.Unicode.GetBytes(Wrapper(root, options, retry))),
                WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
            };
            // stdout and stderr are drained concurrently to avoid pipe deadlocks during a build.
            object gate = new object();
            Exception outputError = null;
            using (var process = new Process { StartInfo = start })
            {
                DataReceivedEventHandler receive = delegate(object sender, DataReceivedEventArgs e) {
                    if (e.Data == null) return;
                    lock (gate) {
                        if (e.Data.StartsWith(Prefix + "begin|")) result.Started = true;
                        if (e.Data.StartsWith(Prefix + "done|")) result.Completed = true;
                        if (e.Data.StartsWith(Prefix + "cancelled|")) result.Cancelled = true;
                        try { output(e.Data); } catch (Exception error) { outputError = error; }
                    }
                };
                process.OutputDataReceived += receive;
                process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) {
                    if (e.Data != null) lock (gate) {
                        try { output("[stderr] " + e.Data); } catch (Exception error) { outputError = error; }
                    }
                };
                process.Start();
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                process.WaitForExit();
                result.ExitCode = process.ExitCode;
                result.Cancelled = result.Cancelled && result.ExitCode == 75;
            }
            if (outputError != null) throw new IOException("설치 출력/로그를 기록하지 못했습니다. 설치가 일부 진행되었을 수 있습니다.", outputError);
            return result;
        }

        internal static RunResult Run(string root, InstallOptions options, Action<string> output)
        {
            ValidateRoot(root);
            var result = RunOnce(root, options, false, output);
            if (CanRetry(result)) {
                output(Prefix + "retry|실행 정책 제한: 이번 설치 프로세스에만 적용하여 한 번 재시도합니다.");
                result = RunOnce(root, options, true, output);
                result.Retried = true;
            }
            return result;
        }

        internal static string Failure(RunResult result)
        {
            if (result.ExitCode == ManagedPolicy || result.ExitCode == PolicyBlocked)
                return "실행 정책 때문에 시작하지 못했습니다. 회사 보안 정책과 스크립트 서명을 관리자에게 확인해 주세요. PC 전체 정책은 변경하지 않았습니다.";
            return "설치를 완료하지 못했습니다 (종료 코드 " + result.ExitCode + "). 상세 로그의 마지막 오류를 확인해 주세요. 네트워크·권한·winget·도구 버전 문제를 해결한 뒤 다시 시도할 수 있습니다. 이미 설치된 도구는 자동 제거되지 않습니다.";
        }
    }
}

using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace NHSetup
{
    internal static class SetupTests
    {
        static int count;
        static void Check(bool condition, string name) {
            if (!condition) throw new Exception("FAIL: " + name);
            count++; Console.WriteLine("PASS: " + name);
        }
        static void Script(string root, string text) {
            File.WriteAllText(Path.Combine(root, "scripts", "bootstrap.ps1"), text, new UTF8Encoding(true));
        }
        static bool UsesBlackText(Control control) {
            if ((control is Label || control is Button || control is CheckBox || control is TextBox)
                && control.ForeColor.ToArgb() != Color.Black.ToArgb()) return false;
            foreach (Control child in control.Controls) if (!UsesBlackText(child)) return false;
            return true;
        }
        static Control Find(Control form, string name) { return form.Controls.Find(name, true)[0]; }
        static void Click(Control form, string name) {
            var button = (Button)Find(form, name);
            // PerformClick outside Application.Run has no persistent UI context.
            // Capture the same context a real Windows message-loop click uses.
            System.Threading.SynchronizationContext.SetSynchronizationContext(new WindowsFormsSynchronizationContext());
            button.PerformClick(); Application.DoEvents();
        }
        static void Until(Func<bool> condition) {
            DateTime deadline = DateTime.UtcNow.AddSeconds(30);
            while (!condition() && DateTime.UtcNow < deadline) { Application.DoEvents(); System.Threading.Thread.Sleep(15); }
            if (!condition()) throw new Exception("GUI condition timed out.");
        }
        static SetupForm TestForm(string root) {
            return new SetupForm(root, path => System.Threading.Tasks.Task.FromResult(0), message => true);
        }
        static void Ready(SetupForm form) {
            form.Show(); Application.DoEvents();
            Click(form, "next"); Click(form, "next"); Click(form, "next"); Until(() => !form.Busy);
        }
        static void Save(Form form, string path, string suffix) {
            Application.DoEvents();
            using (var bitmap = new Bitmap(form.Width, form.Height)) {
                form.DrawToBitmap(bitmap, new Rectangle(0, 0, bitmap.Width, bitmap.Height));
                bitmap.Save(Path.ChangeExtension(path, "." + suffix + ".png"));
            }
        }
        [STAThread]
        static int Main(string[] args) {
            try {
                string repo = args[0];
                Check(File.ReadAllText(Path.Combine(repo, "desktop", "main.py")).Contains("WINDOW_TITLE = \"NH FUTURES API\"") &&
                    File.ReadAllText(Path.Combine(repo, "build", "nhfutures.spec")).Contains("name=\"NH FUTURES API\""), "desktop title and packaged EXE name agree");
                Check(File.ReadAllText(Path.Combine(repo, "frontend", "index.html")).Contains("<title>NH FUTURES API</title>") &&
                    File.ReadAllText(Path.Combine(repo, "frontend", "src", "app", "TopBar.tsx")).Contains(">NH FUTURES API</span>"), "browser title and frontend brand agree");
                Check(File.ReadAllText(Path.Combine(repo, "scripts", "bootstrap.ps1")).Contains("-Name 'NH FUTURES API'"), "desktop shortcut uses the new display name");
                string temp = Path.Combine(Path.GetTempPath(), "NH setup 한글 ' & [경로] " + Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(Path.Combine(temp, "scripts"));
                Directory.CreateDirectory(Path.Combine(temp, "frontend"));
                File.WriteAllText(Path.Combine(temp, "justfile"), "");
                File.WriteAllText(Path.Combine(temp, "pyproject.toml"), "");
                File.WriteAllText(Path.Combine(temp, "frontend", "package.json"), "{}");
                // Fixtures are left in the OS temp folder for diagnosis; no real installers are invoked.
                Console.WriteLine("Fixture folder: " + temp);
                bool rejected = false;
                try { SetupCore.ValidateRoot(temp); } catch (InvalidOperationException) { rejected = true; }
                Check(rejected, "reject incomplete ZIP");
                Check(SetupCore.QuotePS("a'b") == "'a''b'", "PowerShell path quoting");
                Check(SetupCore.CanRetry(new RunResult { ExitCode = 73 }), "retry only policy code before start");
                Check(!SetupCore.CanRetry(new RunResult { ExitCode = 1 }), "no retry for generic failures");
                Check(!SetupCore.CanRetry(new RunResult { ExitCode = 73, Started = true }), "no retry after partial install");
                Check(!SetupCore.CanRetry(new RunResult { ExitCode = 74 }), "no retry of managed policy");
                string wrapper = SetupCore.Wrapper(temp, new InstallOptions { Build = false, Shortcut = false, DryRun = true }, true);
                Check(wrapper.Contains(" -SkipBuild -NoShortcut -DryRun"), "GUI selections mapped to switches");
                Check(wrapper.Contains("Get-ExecutionPolicy -Scope MachinePolicy") && wrapper.Contains("Get-ExecutionPolicy -Scope UserPolicy"), "managed policy checked on fallback");
                Check(!wrapper.Contains("Set-ExecutionPolicy") && !wrapper.Contains("Invoke-Expression"), "no permanent policy change or source evaluation");

                var progress = new InstallProgress(true, true);
                Check(progress.Percent == 0 && progress.Keys.Count == 5, "progress starts at zero with five selected stages");
                progress.Observe("tools"); Check(progress.Percent == 0, "starting first stage is not completion");
                progress.Observe("dependencies"); Check(progress.Percent == 20, "completed tools count as 20 percent");
                progress.Observe("build"); Check(progress.Percent == 40, "completed dependencies count as 40 percent");
                progress.Observe("shortcut"); Check(progress.Percent == 60, "completed build counts as 60 percent");
                progress.Observe("done"); Check(progress.Percent == 80, "done event alone cannot show 100 percent");
                progress.Observe("retry"); progress.Observe("tools"); Check(progress.Percent == 80, "unknown and late stages cannot move progress backward");
                progress.Finish(true); Check(progress.Percent == 100, "confirmed process success reaches 100 percent");
                progress.Observe("dependencies"); Check(progress.Percent == 100, "late output cannot overwrite terminal progress");
                var failureProgress = new InstallProgress(true, false);
                failureProgress.Observe("build"); failureProgress.Finish(false); failureProgress.Observe("done"); failureProgress.Finish(true);
                Check(failureProgress.Percent == 50 && failureProgress.Finished, "failure keeps last completion and cannot become success later");
                var devProgress = new InstallProgress(false, true);
                Check(devProgress.Keys.Count == 3 && !devProgress.Keys.Contains("shortcut"), "dev-only denominator excludes build and shortcut");
                devProgress.Observe("dependencies"); Check(devProgress.Percent == 33, "dev-only percentage recalculated for selected stages");

                var motion = new ProgressAnimation();
                motion.MoveTo(20); Check(motion.Value == 0 && motion.Active, "new target does not jump displayed progress");
                motion.Advance(260); double quarter = motion.Value;
                Check(quarter > 0 && quarter < 5, "easing starts gently rather than jumping or moving linearly");
                motion.Advance(260); Check(Math.Abs(motion.Value - 10) < 0.001, "half duration reaches midpoint");
                motion.Advance(520); Check(motion.Value == 20 && !motion.Active, "animation lands exactly on confirmed target");
                motion.Advance(60000); Check(motion.Value == 20, "idle time cannot invent progress");
                motion.MoveTo(40); motion.Advance(200); double retargeted = motion.Value;
                motion.MoveTo(80); Check(motion.Value == retargeted, "rapid stage updates retarget from current display without snapping");
                motion.MoveTo(60); Check(motion.Target == 80, "late lower targets cannot reverse display");
                bool bounded = true;
                for (int i = 0; i < 120; i++) {
                    double before = motion.Value; motion.Advance(16);
                    bounded &= motion.Value >= before && motion.Value <= 80;
                }
                Check(bounded && motion.Value == 80, "all intermediate frames are monotonic and bounded by confirmed work");
                motion.MoveTo(100); motion.Advance(1039);
                Check((int)motion.Value < 100, "display cannot round up to 100 before animation completes");
                motion.Advance(100000); Check(motion.Value == 100 && !motion.Active, "delayed timer catches up without overshoot");
                motion.Reset(); Check(motion.Value == 0 && motion.Target == 0 && !motion.Active, "retry resets display immediately with no previous animation left");

                for (int build = 0; build < 2; build++) for (int shortcut = 0; shortcut < 2; shortcut++) {
                    var lines = new List<string>();
                    var result = SetupCore.RunOnce(repo, new InstallOptions { Build = build == 1, Shortcut = shortcut == 1, DryRun = true }, true, lines.Add);
                    Check(result.Success, "real bootstrap dry-run succeeds " + build + "/" + shortcut);
                    Check(!lines.Exists(x => x.Contains("CLIXML") || x.Contains("<Objs Version=")), "host messages stay plain text " + build + "/" + shortcut);
                    Check(lines.Exists(x => x.StartsWith("NHSETUP|build|")) == (build == 1), "dry-run build selection " + build + "/" + shortcut);
                    Check(lines.Exists(x => x.StartsWith("NHSETUP|shortcut|")) == (build == 1 && shortcut == 1), "dry-run shortcut selection " + build + "/" + shortcut);
                }

                Script(temp, "param([switch]$NonInteractive)\nWrite-Output 'NHSETUP|begin|한글 시작'\nWrite-Output 'NHSETUP|done|완료'");
                var received = new List<string>();
                Check(SetupCore.RunOnce(temp, new InstallOptions(), true, received.Add).Success, "Unicode/spaces/quotes/brackets path invocation");
                Check(received.Contains("NHSETUP|done|완료"), "UTF-8 output preserved");
                string previous = Environment.GetEnvironmentVariable("PSExecutionPolicyPreference");
                try {
                    Environment.SetEnvironmentVariable("PSExecutionPolicyPreference", "Restricted");
                    var retry = SetupCore.Run(temp, new InstallOptions(), delegate(string line) { });
                    Check(retry.Success && retry.Retried, "actual Restricted process policy: fail once, then process-only retry");
                } finally { Environment.SetEnvironmentVariable("PSExecutionPolicyPreference", previous); }

                Script(temp, "param([switch]$NonInteractive)\nWrite-Output 'NHSETUP|begin|start'\nthrow 'simulated build failure'");
                var failed = SetupCore.RunOnce(temp, new InstallOptions(), true, delegate(string line) { });
                Check(failed.ExitCode == 1 && failed.Started && !failed.Success, "build failure surfaced");
                Script(temp, "param([switch]$NonInteractive)\nWrite-Output 'NHSETUP|begin|start'\nthrow [System.Management.Automation.PSSecurityException]::new('blocked after start')");
                var partial = SetupCore.RunOnce(temp, new InstallOptions(), true, delegate(string line) { });
                Check(partial.ExitCode == 1 && !SetupCore.CanRetry(partial), "security error after begin is not policy fallback");
                Script(temp, "param([switch]$NonInteractive)\nWrite-Output 'NHSETUP|begin|start'");
                Check(!SetupCore.RunOnce(temp, new InstallOptions(), true, delegate(string line) { }).Success, "exit zero without done is not success");
                Script(temp, "param([switch]$NonInteractive)\nWrite-Output 'NHSETUP|begin|start'\n[Console]::Error.WriteLine('NHSETUP|done|fake')");
                Check(!SetupCore.RunOnce(temp, new InstallOptions(), true, delegate(string line) { }).Success, "stderr cannot spoof completion");
                Script(temp, "param([switch]$NonInteractive)\nWrite-Output 'NHSETUP|begin|start'\n1..2000 | ForEach-Object { Write-Output ('out' + $_); [Console]::Error.WriteLine('err' + $_) }; Write-Output 'NHSETUP|done|done'");
                int messages = 0;
                Check(SetupCore.RunOnce(temp, new InstallOptions(), true, delegate(string line) { messages++; }).Success && messages == 4002, "concurrent stdout/stderr drained completely");
                bool outputFailed = false;
                try { SetupCore.RunOnce(temp, new InstallOptions(), true, delegate(string line) { throw new IOException("mock full disk"); }); }
                catch (IOException) { outputFailed = true; }
                Check(outputFailed, "log failures reported without crashing output worker");

                // Exercise the real installation branches with command functions replacing every tool.
                // No winget, npm, uv or just executable is allowed to run in these fixtures.
                string actualBootstrap = File.ReadAllText(Path.Combine(repo, "scripts", "bootstrap.ps1"));
                File.WriteAllText(Path.Combine(temp, "scripts", "bootstrap.real.ps1"), actualBootstrap, new UTF8Encoding(true));
                string mocks = "param([switch]$NonInteractive,[switch]$SkipBuild,[switch]$NoShortcut,[switch]$DryRun)\n" +
                    "function node { 'v22.15.0' }; function uv { 'uv 0.8.0' }; function winget { throw 'Unexpected winget invocation' };\n" +
                    "function just { param([string]$Recipe) $global:LASTEXITCODE=0; if ($Recipe -eq '--version') { 'just 1.40.0'; return }; " +
                    "Write-Output ('MOCK_JUST|' + $Recipe); if ($Recipe -eq 'package') { " +
                    "$dir=Join-Path (Split-Path -Parent $PSScriptRoot) 'desktop/dist'; [IO.Directory]::CreateDirectory($dir) | Out-Null; " +
                    "[IO.File]::WriteAllText((Join-Path $dir 'NH FUTURES API.exe'),'fixture, not executable') } };\n" +
                    "& (Join-Path $PSScriptRoot 'bootstrap.real.ps1') -NonInteractive -SkipBuild:$SkipBuild -NoShortcut:$NoShortcut -DryRun:$DryRun";
                Script(temp, mocks);
                var mockLines = new List<string>();
                Check(SetupCore.RunOnce(temp, new InstallOptions { Shortcut = false }, true, mockLines.Add).Success, "real install flow with mocked tools succeeds");
                Check(mockLines.FindAll(x => x == "MOCK_JUST|package").Count == 1 && !mockLines.Contains("MOCK_JUST|build"), "package once, no duplicate frontend build");
                Check(mockLines.Contains("MOCK_JUST|setup"), "dependencies installed by shared bootstrap");
                mockLines.Clear();
                Check(SetupCore.RunOnce(temp, new InstallOptions { Build = false, Shortcut = false }, true, mockLines.Add).Success && !mockLines.Contains("MOCK_JUST|package"), "dev-only selection skips packaging without prompting");
                Script(temp, mocks.Replace("Write-Output ('MOCK_JUST|' + $Recipe);", "if ($Recipe -eq 'setup') { $global:LASTEXITCODE=42; return }; Write-Output ('MOCK_JUST|' + $Recipe);"));
                mockLines.Clear();
                var dependencyFailure = SetupCore.RunOnce(temp, new InstallOptions { Shortcut = false }, true, mockLines.Add);
                Check(!dependencyFailure.Success && dependencyFailure.Started && !mockLines.Contains("MOCK_JUST|package"), "dependency failure prevents packaging and completion");

                // A fresh folder avoids a previously built fixture masking missing-artifact detection.
                string artifact = Path.Combine(temp, "desktop", "dist", "NH FUTURES API.exe");
                File.Move(artifact, artifact + ".saved");
                Script(temp, mocks.Replace("[IO.File]::WriteAllText((Join-Path $dir 'NH FUTURES API.exe'),'fixture, not executable')", "Write-Output 'MOCK_NO_ARTIFACT'"));
                Check(!SetupCore.RunOnce(temp, new InstallOptions { Shortcut = false }, true, delegate(string line) { }).Success, "successful packager without EXE is rejected");

                string upgrade = mocks.Replace("function node { 'v22.15.0' }", "$global:setupTestNode='18.0.0'; function node { $global:setupTestNode }")
                    .Replace("function winget { throw 'Unexpected winget invocation' }", "function winget { Write-Output ('MOCK_WINGET|' + ($args -join ' ')); $global:setupTestNode='22.15.0'; $global:LASTEXITCODE=0 }");
                Script(temp, upgrade);
                mockLines.Clear();
                Check(SetupCore.RunOnce(temp, new InstallOptions { Build = false, Shortcut = false }, true, mockLines.Add).Success, "old Node upgraded through mocked winget and rechecked");
                Check(mockLines.Exists(x => x.StartsWith("MOCK_WINGET|") && x.Contains("--silent --disable-interactivity") && x.Contains("--accept-source-agreements --accept-package-agreements") && x.Contains("OpenJS.NodeJS.LTS")), "GUI installation uses exact package and noninteractive flags");
                Script(temp, upgrade.Replace("$global:setupTestNode='22.15.0'; $global:LASTEXITCODE=0", "$global:LASTEXITCODE=0"));
                Check(!SetupCore.RunOnce(temp, new InstallOptions { Build = false, Shortcut = false }, true, delegate(string line) { }).Success, "old Node still first on PATH is a failure");


                string checkMocks = mocks.Replace("[switch]$DryRun)", "[switch]$DryRun,[switch]$CheckOnly,[string]$CancellationFile)")
                    .Replace("-DryRun:$DryRun", "-DryRun:$DryRun -CheckOnly:$CheckOnly -CancellationFile $CancellationFile");
                Script(temp, checkMocks);
                mockLines.Clear();
                Check(SetupCore.RunOnce(temp, new InstallOptions { CheckOnly = true }, true, mockLines.Add).Success, "read-only tool preflight succeeds");
                Check(!mockLines.Exists(x => x.StartsWith("MOCK_JUST|")), "preflight does not install dependencies or build");
                Check(SetupCore.ToolSummary(string.Join("\n", mockLines)).Contains("Node.js: 22.15.0") &&
                    SetupCore.ToolSummary(string.Join("\n", mockLines)).Contains("uv: 0.8.0"), "tool status summary is parsed");
                Check(SetupCore.ValidateWritableRoot(temp) == Path.GetFullPath(temp) &&
                    Directory.GetFiles(temp, ".nh-setup-write-*").Length == 0, "location validation removes only its own write probe");
                string cancelPath = Path.Combine(temp, "request.cancel");
                File.WriteAllText(cancelPath, "cancel");
                var cancelled = SetupCore.RunOnce(temp, new InstallOptions { CancellationFile = cancelPath }, true, mockLines.Add);
                Check(cancelled.Cancelled && cancelled.ExitCode == 75 && !cancelled.Success && !SetupCore.CanRetry(cancelled), "pre-start cancellation is distinct and not retried");
                File.Delete(cancelPath);
                string cancelDuringSetup = checkMocks.Replace("Write-Output ('MOCK_JUST|' + $Recipe);",
                    "Write-Output ('MOCK_JUST|' + $Recipe); if ($Recipe -eq 'setup') { [IO.File]::WriteAllText($CancellationFile,'cancel') };");
                Script(temp, cancelDuringSetup); mockLines.Clear();
                cancelled = SetupCore.RunOnce(temp, new InstallOptions { CancellationFile = cancelPath }, true, mockLines.Add);
                Check(cancelled.Cancelled && mockLines.Contains("MOCK_JUST|setup") &&
                    !mockLines.Contains("MOCK_JUST|package"), "cancellation after dependencies prevents the next build");
                File.Delete(cancelPath);
                // With no build selected, dependencies are the last step: a cancel request written during it must not
                // turn a finished installation into a cancelled one.
                mockLines.Clear();
                var finished = SetupCore.RunOnce(temp, new InstallOptions { Build = false, Shortcut = false, CancellationFile = cancelPath }, true, mockLines.Add);
                Check(finished.Success && !finished.Cancelled && mockLines.Contains("MOCK_JUST|setup") && File.Exists(cancelPath), "cancellation during the last step still reports completion");
                File.Delete(cancelPath);

                string launchRoot = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "launch-fixture");
                string launchDir = Path.Combine(launchRoot, "desktop", "dist");
                SetupCore.LaunchApplication(launchRoot).GetAwaiter().GetResult();
                Check(File.Exists(Path.Combine(launchDir, "started")) && !File.Exists(Path.Combine(launchDir, "finished")), "launcher returns while independent fixture process is alive");
                DateTime launchDeadline = DateTime.UtcNow.AddSeconds(10);
                while (!File.Exists(Path.Combine(launchDir, "finished")) && DateTime.UtcNow < launchDeadline) System.Threading.Thread.Sleep(20);
                Check(File.Exists(Path.Combine(launchDir, "finished")), "disposing launcher process handle does not terminate the child");
                File.WriteAllText(Path.Combine(launchDir, "exit-early"), "");
                bool earlyExit = false;
                try { SetupCore.LaunchApplication(launchRoot).GetAwaiter().GetResult(); }
                catch (InvalidOperationException) { earlyExit = true; }
                Check(earlyExit, "launcher rejects an immediately exiting executable");
                File.Delete(Path.Combine(launchDir, "exit-early"));
                bool missingExe = false;
                try { SetupCore.LaunchApplication(Path.Combine(temp, "missing-app")).GetAwaiter().GetResult(); }
                catch (FileNotFoundException) { missingExe = true; }
                Check(missingExe, "launcher rejects a missing app");

                if (args.Length > 1) {
                    Application.EnableVisualStyles();
                    Application.SetCompatibleTextRenderingDefault(false);
                    // All GUI runs use offline command fixtures. No installs, shortcut COM calls, or NH requests.
                    Script(temp, checkMocks);
                    using (var form = new SetupForm(temp, path => System.Threading.Tasks.Task.FromResult(0), message => true)) {
                        form.Show(); Application.DoEvents();
                        Check(form.Text == "NH FUTURES API 설치" && form.ClientSize == new Size(600, 450), "compact 600x450 branded installer");
                        Check(form.Page == SetupPage.Welcome && !form.Busy, "opening installer does not start installation");
                        Check(UsesBlackText(form), "all UI text uses black foreground");
                        Save(form, args[1], "welcome");
                        Click(form, "next"); Check(form.Page == SetupPage.Location, "welcome advances to location"); Save(form, args[1], "location");
                        Click(form, "next"); Check(form.Page == SetupPage.Options, "valid project location advances to options");
                        var build = (CheckBox)Find(form, "build"); var shortcut = (CheckBox)Find(form, "shortcut"); var consent = (CheckBox)Find(form, "consent");
                        Check(build.Checked && shortcut.Checked && consent.Checked, "all three options default selected");
                        consent.Checked = false; Check(!Find(form, "next").Enabled, "consent required before installation preparation"); consent.Checked = true;
                        build.Checked = false; Check(!shortcut.Enabled && shortcut.Checked, "build disabled preserves shortcut choice but disables it"); build.Checked = true;
                        Save(form, args[1], "options");
                        Click(form, "next"); Until(() => !form.Busy);
                        Check(form.Page == SetupPage.Ready && Find(form, "next").Enabled && Find(form, "tools").Text.Contains("22.15.0"), "ready page shows actual checked tool versions");
                        Save(form, args[1], "ready");
                        Click(form, "back"); Check(form.Page == SetupPage.Options && build.Checked, "back preserves choices");
                        Click(form, "next"); Until(() => !form.Busy);
                        Click(form, "preview"); Until(() => !form.Busy && Find(form, "percent").Text == "100%");
                        Check(form.Page == SetupPage.Finished && Find(form, "status").Text.StartsWith("미리보기 완료"), "preview completes without installation");
                        Check(Find(form, "next").Text == "설치 준비로", "preview cannot launch an uninstalled application");
                        Click(form, "details"); Check(Find(form, "log").Visible, "logs expand on demand"); Save(form, args[1], "preview");
                        form.Close();
                    }

                    // A slow failing build demonstrates honest eased percentages and retry routing.
                    string slowFailure = checkMocks.Replace("Write-Output ('MOCK_JUST|' + $Recipe);",
                        "Write-Output ('MOCK_JUST|' + $Recipe); if ($Recipe -eq 'package') { Start-Sleep -Seconds 3; throw 'fixture build failure' };");
                    Script(temp, slowFailure);
                    using (var form = TestForm(temp)) {
                        Ready(form);
                        Click(form, "next");
                        var track = (ProgressTrack)Find(form, "progress");
                        Until(() => track.Value > 10 && track.Value < 40);
                        Check(form.Busy && Find(form, "percent").Text == ((int)track.Value) + "%", "timer displays eased intermediate progress");
                        Save(form, args[1], "progress");
                        Until(() => !form.Busy && Find(form, "percent").Text == "40%");
                        Check(form.Page == SetupPage.Finished && Find(form, "log").Visible && Find(form, "next").Text == "설치 준비로", "failure preserves 40 percent and exposes logs");
                        Check(UsesBlackText(form), "failure and log text stay black"); Save(form, args[1], "failure");
                        Click(form, "next"); Until(() => !form.Busy);
                        Check(form.Page == SetupPage.Ready, "retry returns to review without starting another install"); form.Close();
                    }

                    // Requesting close during work queues cancellation, leaving the current command alive.
                    Script(temp, checkMocks.Replace("Write-Output ('MOCK_JUST|' + $Recipe);",
                        "Write-Output ('MOCK_JUST|' + $Recipe); if ($Recipe -eq 'setup') { Start-Sleep -Seconds 2; Write-Output 'MOCK_CURRENT_TASK_FINISHED' };"));
                    using (var form = TestForm(temp)) {
                        Ready(form); Click(form, "next");
                        Until(() => Find(form, "log").Text.Contains("MOCK_JUST|setup"));
                        form.Close();
                        Check(!form.IsDisposed && form.CancellationRequested, "closing running installer queues safe cancellation");
                        Until(() => !form.Busy);
                        Check(Find(form, "status").Text.StartsWith("설치를 중단") && Find(form, "log").Text.Contains("MOCK_CURRENT_TASK_FINISHED") &&
                            !Find(form, "log").Text.Contains("MOCK_JUST|package"), "cancel waits for current work and skips following build");
                        Save(form, args[1], "cancelled"); form.Close();
                    }

                    // Completion keeps the app launch explicit; a failed launch must keep the installer open.
                    Script(temp, checkMocks);
                    bool launched = false;
                    var pending = new System.Threading.Tasks.TaskCompletionSource<int>();
                    using (var form = new SetupForm(temp, path => {
                        launched = true; return pending.Task;
                    }, message => true)) {
                        Ready(form); ((Button)Find(form, "back")).PerformClick();
                        ((CheckBox)Find(form, "shortcut")).Checked = false;
                        Click(form, "next"); Until(() => !form.Busy); Click(form, "next");
                        Until(() => !form.Busy && Find(form, "percent").Text == "100%");
                        Check(!launched && Find(form, "next").Text == "실행하기", "successful install waits for explicit launch");
                        Save(form, args[1], "complete");
                        Click(form, "next"); form.Close();
                        Check(launched && !form.IsDisposed && form.Busy, "launch wait disables duplicate launch and premature close");
                        pending.SetException(new IOException("fixture launch failure")); Until(() => !form.Busy);
                        Check(!form.IsDisposed && Find(form, "status").Text.Contains("시작하지 못했습니다") && Find(form, "log").Visible, "launch failure keeps installer and error details");
                        Save(form, args[1], "launch-failure"); form.Close();
                    }
                    File.Delete(Path.Combine(launchDir, "finished"));
                    using (var form = new SetupForm(temp, path => SetupCore.LaunchApplication(launchRoot), message => true)) {
                        Ready(form); Click(form, "back"); ((CheckBox)Find(form, "shortcut")).Checked = false;
                        Click(form, "next"); Until(() => !form.Busy); Click(form, "next"); Until(() => !form.Busy && Find(form, "percent").Text == "100%");
                        Click(form, "next"); Until(() => form.IsDisposed);
                        Check(form.IsDisposed, "successful explicit launch automatically closes the installer");
                        Until(() => File.Exists(Path.Combine(launchDir, "finished")));
                        Check(true, "launched fixture finishes normally after the installer closes");
                    }
                    using (var form = TestForm(temp)) {
                        form.Show(); Click(form, "next"); Click(form, "next"); ((CheckBox)Find(form, "build")).Checked = false;
                        Click(form, "next"); Until(() => !form.Busy); Click(form, "next"); Until(() => !form.Busy && Find(form, "percent").Text == "100%");
                        Check(Find(form, "next").Text == "닫기" && Find(form, "status").Text.Contains("just dev"), "dev-only completion offers close instead of launching stale EXE");
                        Check(!Find(form, "cancel").Visible, "dev-only completion has only one close button");
                        Save(form, args[1], "dev-only");
                        form.Scale(new SizeF(1.5F, 1.5F)); Application.DoEvents(); Save(form, args[1], "scaled");
                        Check(Find(form, "next").Visible && Find(form, "status").Visible, "scaled layout retains navigation and status");
                        Click(form, "next"); Check(form.IsDisposed, "dev-only close finishes installer");
                    }
                }
                Console.WriteLine("TOTAL PASS: " + count);
                return 0;
            } catch (Exception error) { Console.Error.WriteLine(error); return 1; }
        }
    }
}

using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace NHSetup
{
    internal static class SetupTheme
    {
        internal static readonly Color Accent = Color.FromArgb(0, 128, 103);
        internal static readonly Color Border = Color.FromArgb(216, 216, 216);
    }

    internal sealed class ProgressTrack : Control
    {
        double value;
        internal double Value { get { return value; } set { this.value = Math.Max(0, Math.Min(100, value)); Invalidate(); } }
        internal ProgressTrack() { Name = "progress"; DoubleBuffered = true; SetStyle(ControlStyles.ResizeRedraw, true); }
        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            if (Width < 3 || Height < 3) return;
            e.Graphics.Clear(Color.FromArgb(240, 240, 240));
            using (var brush = new SolidBrush(SetupTheme.Accent))
                e.Graphics.FillRectangle(brush, 1, 1, (int)((Width - 2) * Value / 100), Height - 2);
            using (var pen = new Pen(SetupTheme.Border))
                e.Graphics.DrawRectangle(pen, 0, 0, Width - 1, Height - 1);
        }
    }

    internal enum SetupPage { Welcome, Location, Options, Ready, Progress, Finished }

    internal sealed class SetupForm : Form
    {
        string root, logPath, cancelFile;
        bool running, checking, launching, cancelRequested, completed, previewed, allowClose, prepared;
        readonly Func<string, Task> startApplication;
        readonly Func<string, bool> confirm;
        readonly Panel body = new Panel { Dock = DockStyle.Fill, Padding = new Padding(24, 18, 24, 12) };
        readonly Label heading = new Label { AutoSize = true, Location = new Point(24, 16) };
        readonly Label step = new Label { AutoSize = true, Location = new Point(24, 48) };
        readonly Button back = Button("back", "< 이전");
        readonly Button next = Button("next", "다음 >");
        readonly Button cancel = Button("cancel", "취소");
        readonly TextBox location = new TextBox { Name = "location", Dock = DockStyle.Fill };
        readonly CheckBox build = Choice("build", "프로그램 실행 파일 만들기");
        readonly CheckBox shortcut = Choice("shortcut", "바탕화면에 바로가기 만들기");
        readonly CheckBox consent = Choice("consent", "필요한 도구 다운로드 및 설치에 동의합니다.");
        readonly Label summary = TextLabel("");
        readonly TextBox tools = new TextBox { Name = "tools", Multiline = true, ReadOnly = true, Dock = DockStyle.Top, Height = 90, BorderStyle = BorderStyle.FixedSingle, ScrollBars = ScrollBars.Vertical };
        readonly Button preview = Button("preview", "작업 미리보기");
        readonly Label status = TextLabel("");
        readonly Label percent = new Label { Name = "percent", Text = "0%", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleRight };
        readonly ProgressTrack track = new ProgressTrack { Dock = DockStyle.Fill, Margin = new Padding(0, 3, 0, 3) };
        readonly Button details = Button("details", "상세 로그 보기");
        readonly Button logs = Button("logs", "로그 폴더");
        readonly TextBox log = new TextBox { Name = "log", Multiline = true, ReadOnly = true, Dock = DockStyle.Fill, ScrollBars = ScrollBars.Both, WordWrap = false, Visible = false };
        readonly Panel[] pages = new Panel[5];
        readonly ProgressAnimation animation = new ProgressAnimation();
        readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer { Interval = 16 };
        readonly Stopwatch clock = new Stopwatch();
        InstallProgress meter;
        internal SetupPage Page { get; private set; }
        internal bool Busy { get { return running || checking || launching; } }
        internal bool CancellationRequested { get { return cancelRequested; } }

        static Button Button(string name, string text) { return new Button { Name = name, Text = text, Size = new Size(96, 28), ForeColor = Color.Black, UseVisualStyleBackColor = true, Margin = new Padding(6, 0, 0, 0) }; }
        static CheckBox Choice(string name, string text) { return new CheckBox { Name = name, Text = text, Checked = true, AutoSize = true, Dock = DockStyle.Top, Padding = new Padding(0, 8, 0, 8) }; }
        static Label TextLabel(string text) { return new Label { Text = text, AutoSize = true, Dock = DockStyle.Top, Padding = new Padding(0, 0, 0, 12) }; }
        static void Stack(Panel panel, params Control[] controls) { for (int i = controls.Length - 1; i >= 0; i--) panel.Controls.Add(controls[i]); }

        internal SetupForm(string project) : this(project, SetupCore.LaunchApplication, null) { }
        // Offline GUI tests inject a launcher so they never start the trading application.
        internal SetupForm(string project, Func<string, Task> launcher, Func<string, bool> confirmation)
        {
            root = project; startApplication = launcher;
            confirm = confirmation ?? (message => MessageBox.Show(this, message, Text, MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes);
            Text = "NH FUTURES API 설치";
            Font = new Font("Malgun Gothic", 9F);
            ForeColor = Color.Black; BackColor = Color.White;
            AutoScaleDimensions = new SizeF(96, 96); AutoScaleMode = AutoScaleMode.Dpi;
            ClientSize = new Size(600, 450); MinimumSize = new Size(616, 489);
            StartPosition = FormStartPosition.CenterScreen; MaximizeBox = false;
            heading.Font = new Font(Font.FontFamily, 13F, FontStyle.Bold);
            var header = new Panel { Dock = DockStyle.Top, Height = 82 };
            header.Controls.Add(heading); header.Controls.Add(step);
            header.Controls.Add(new Panel { Dock = DockStyle.Bottom, Height = 1, BackColor = SetupTheme.Border });
            var footer = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 56, BackColor = Color.FromArgb(245, 245, 245), FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(12, 13, 18, 0), WrapContents = false };
            footer.Controls.Add(cancel); footer.Controls.Add(next); footer.Controls.Add(back);
            Controls.Add(body); Controls.Add(footer); Controls.Add(header);
            for (int i = 0; i < pages.Length; i++) {
                pages[i] = new Panel { Dock = DockStyle.Fill, AutoScroll = true };
                body.Controls.Add(pages[i]);
            }
            Stack(pages[0], TextLabel("NH FUTURES API를 설치합니다."),
                TextLabel("개발 도구와 프로젝트 의존성을 준비하고, 선택에 따라 실행 파일과 바탕화면 바로가기를 만듭니다."),
                TextLabel("인터넷 연결이 필요합니다. 설치된 도구는 버전을 확인하여 재사용합니다."),
                TextLabel("계좌와 APP Key / Secret은 설치 후 프로그램의 설정에서 입력합니다. 계속하려면 다음을 누르세요."));
            location.Text = root;
            var folderRow = new TableLayoutPanel { Dock = DockStyle.Top, Height = 38, ColumnCount = 2 };
            folderRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            folderRow.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 100));
            var browse = Button("browse", "찾아보기...");
            folderRow.Controls.Add(location, 0, 0); folderRow.Controls.Add(browse, 1, 0);
            browse.Click += delegate {
                using (var dialog = new FolderBrowserDialog { SelectedPath = location.Text, Description = "ZIP의 압축을 모두 푼 프로젝트 폴더를 선택하세요.", ShowNewFolderButton = false })
                    if (dialog.ShowDialog(this) == DialogResult.OK) location.Text = dialog.SelectedPath;
            };
            Stack(pages[1], TextLabel("설치 위치 (압축을 푼 프로젝트 폴더)"), folderRow,
                TextLabel("이 폴더에서 의존성과 실행 파일을 만듭니다. 빈 폴더로 파일을 복사하거나 기존 프로젝트를 이동하지 않습니다."),
                TextLabel("위치를 바꾸려면 전체 ZIP을 원하는 곳에 먼저 풀고 해당 프로젝트 폴더를 선택하세요."));
            Stack(pages[2], TextLabel("설치할 항목을 선택하세요."), build, shortcut, consent,
                TextLabel("실행 파일 만들기를 끄면 개발 도구와 의존성만 설치합니다. 회사 보안 정책과 권한에 따라 설치가 제한될 수 있습니다."));
            build.CheckedChanged += delegate { shortcut.Enabled = build.Checked; };
            consent.CheckedChanged += delegate { RenderButtons(); };
            Stack(pages[3], summary, tools, new Panel { Dock = DockStyle.Top, Height = 10 }, preview,
                TextLabel("설치 시작을 누르면 선택한 작업을 진행합니다. 미리보기는 다운로드나 설치를 하지 않습니다."));
            preview.Dock = DockStyle.Top;
            status.Name = "status";
            var progressRow = new TableLayoutPanel { Dock = DockStyle.Top, Height = 30, ColumnCount = 2 };
            progressRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); progressRow.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 48));
            progressRow.Controls.Add(track, 0, 0); progressRow.Controls.Add(percent, 1, 0);
            var support = new FlowLayoutPanel { Dock = DockStyle.Top, Height = 38, Padding = new Padding(0, 4, 0, 0), WrapContents = false };
            var folder = Button("folder", "프로젝트 폴더"); folder.Width = 112;
            details.Width = 116;
            support.Controls.Add(details); support.Controls.Add(logs); support.Controls.Add(folder);
            pages[4].Controls.Add(log);
            Stack(pages[4], status, progressRow, TextLabel("진행률은 완료된 작업 단계 기준입니다. 다운로드 속도나 남은 시간을 뜻하지 않습니다."), support);
            details.Click += delegate { ToggleLog(!log.Visible); };
            logs.Click += delegate { Open(Path.GetDirectoryName(logPath)); };
            folder.Click += delegate { Open(root); };
            preview.Click += async delegate { await Install(true); };
            next.Click += async delegate { await Next(); };
            back.Click += delegate { if (!Busy && Page > SetupPage.Welcome && Page < SetupPage.Progress) ShowPage(Page - 1); };
            cancel.Click += delegate { Close(); };
            FormClosing += delegate(object sender, FormClosingEventArgs e) {
                if (allowClose) return;
                if (running) { e.Cancel = true; RequestCancellation(); }
                else if (checking || launching) e.Cancel = true;
                else if (Page != SetupPage.Finished && !confirm("설치를 종료할까요?")) e.Cancel = true;
            };
            timer.Tick += delegate {
                double elapsed = clock.Elapsed.TotalMilliseconds; clock.Restart();
                animation.Advance(elapsed); track.Value = animation.Value; percent.Text = ((int)animation.Value) + "%";
            };
            clock.Start(); timer.Start();
            body.SizeChanged += delegate { FitLabels(body); };
            ShowPage(SetupPage.Welcome);
        }

        void FitLabels(Control parent)
        {
            foreach (Control child in parent.Controls) {
                var label = child as Label;
                if (label != null && label.AutoSize) label.MaximumSize = new Size(Math.Max(100, body.ClientSize.Width - body.Padding.Horizontal - 20), 0);
                FitLabels(child);
            }
        }
        void ShowPage(SetupPage page)
        {
            Page = page;
            for (int i = 0; i < pages.Length; i++) pages[i].Visible = i == Math.Min(4, (int)page);
            heading.Text = new[] { "설치 안내", "설치 위치", "설치 옵션", "설치 준비", "설치 중", "설치 결과" }[(int)page];
            step.Text = "NH FUTURES API  ·  " + ((int)page + 1) + " / 6";
            FitLabels(body); RenderButtons();
        }
        void RenderButtons()
        {
            back.Visible = Page > SetupPage.Welcome && Page < SetupPage.Progress; back.Enabled = !Busy;
            next.Visible = Page != SetupPage.Progress;
            next.Enabled = !Busy && (Page != SetupPage.Options || consent.Checked) && (Page != SetupPage.Ready || (consent.Checked && prepared));
            next.Text = Page == SetupPage.Ready ? "설치 시작" : Page == SetupPage.Finished ?
                (completed && !previewed ? (build.Checked ? "실행하기" : "닫기") : "설치 준비로") : "다음 >";
            cancel.Text = Page == SetupPage.Finished ? "닫기" : cancelRequested ? "취소 대기" : "취소";
            cancel.Visible = !(Page == SetupPage.Finished && completed && !previewed && !build.Checked);
            cancel.Enabled = !checking && !launching && !cancelRequested;
            preview.Enabled = !Busy;
            logs.Enabled = logPath != null && File.Exists(logPath);
            AcceptButton = next.Visible && next.Enabled ? next : null;
        }
        async Task Next()
        {
            if (Busy) return;
            if (Page == SetupPage.Location) {
                try { root = SetupCore.ValidateWritableRoot(location.Text.Trim()); location.Text = root; }
                catch (Exception error) { MessageBox.Show(this, error.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Warning); return; }
            }
            if (Page == SetupPage.Options) { await Prepare(); return; }
            if (Page == SetupPage.Ready) { await Install(false); return; }
            if (Page == SetupPage.Finished) {
                if (!completed || previewed) { await Prepare(); return; }
                if (!build.Checked) { allowClose = true; Close(); return; }
                launching = true; RenderButtons(); status.Text = "프로그램을 시작하고 있습니다...";
                try { await startApplication(root); allowClose = true; Close(); }
                catch (Exception error) {
                    status.Text = "프로그램을 시작하지 못했습니다. 설치 창을 유지합니다.";
                    RecordError(error); ToggleLog(true);
                }
                finally { launching = false; if (!IsDisposed) RenderButtons(); }
                return;
            }
            ShowPage(Page + 1);
        }
        async Task Prepare()
        {
            checking = true; prepared = false;
            summary.Text = "위치: " + root + Environment.NewLine +
                "설치 항목: 개발 도구 · 의존성" + (build.Checked ? " · 실행 파일" : "") + (build.Checked && shortcut.Checked ? " · 바로가기" : "");
            tools.Text = "설치된 도구 버전을 확인하고 있습니다...";
            ShowPage(SetupPage.Ready);
            try {
                var lines = new StringBuilder();
                var result = await Task.Run(() => SetupCore.Run(root, new InstallOptions { CheckOnly = true }, line => lines.AppendLine(line)));
                prepared = result.Success;
                tools.Text = prepared ? SetupCore.ToolSummary(lines.ToString()) : SetupCore.Failure(result) + Environment.NewLine + lines;
            }
            catch (Exception error) { tools.Text = "도구 확인 실패: " + error.Message; }
            finally { checking = false; RenderButtons(); }
        }
        void ToggleLog(bool visible)
        {
            log.Visible = visible; details.Text = visible ? "상세 로그 숨기기" : "상세 로그 보기";
            if (visible) { log.SelectionStart = log.TextLength; log.SelectionLength = 0; log.ScrollToCaret(); }
        }
        void RequestCancellation()
        {
            if (cancelRequested || !confirm("현재 작업이 끝난 뒤 설치를 중단할까요? 실행 중인 설치 도구는 강제 종료하지 않으며, 이미 설치된 항목은 유지됩니다.")) return;
            // A modal confirmation pumps messages; installation may finish while it is open.
            if (!running || cancelFile == null) return;
            try {
                File.WriteAllText(cancelFile, "cancel");
                cancelRequested = true; status.Text = "취소 대기 중 — 현재 작업이 끝나면 중단합니다."; RenderButtons();
            } catch (Exception error) { MessageBox.Show(this, "취소 요청을 저장하지 못했습니다: " + error.Message, Text); }
        }
        void Append(string line)
        {
            log.AppendText(line + Environment.NewLine);
            if (!line.StartsWith(SetupCore.Prefix)) return;
            string[] parts = line.Split(new[] { '|' }, 3);
            if (parts.Length < 3) return;
            meter.Observe(parts[1]); animation.MoveTo(meter.Percent);
            if (!cancelRequested && running) status.Text = parts[2];
        }
        async Task Install(bool dryRun)
        {
            if (Busy || (!dryRun && (!prepared || !consent.Checked))) return;
            running = true; completed = false; previewed = dryRun; cancelRequested = false;
            logPath = cancelFile = null;
            meter = new InstallProgress(build.Checked, shortcut.Checked);
            animation.Reset(); track.Value = 0; percent.Text = "0%"; log.Clear(); ToggleLog(false);
            status.Text = dryRun ? "작업 미리보기 중..." : "설치를 시작합니다...";
            ShowPage(SetupPage.Progress);
            try {
                string directory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "NHFutures", "Setup", "logs");
                Directory.CreateDirectory(directory);
                logPath = Path.Combine(directory, DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N") + ".log");
                cancelFile = logPath + ".cancel";
                var options = new InstallOptions { Build = build.Checked, Shortcut = shortcut.Checked, DryRun = dryRun, CancellationFile = cancelFile };
                RunResult result;
                using (var writer = new StreamWriter(logPath, false, new UTF8Encoding(true)) { AutoFlush = true }) {
                    logs.Enabled = true;
                    result = await Task.Run(() => SetupCore.Run(root, options, line => {
                        writer.WriteLine(line);
                        BeginInvoke(new Action(() => Append(line)));
                    }));
                }
                completed = result.Success; meter.Finish(completed); animation.MoveTo(meter.Percent);
                status.Text = result.Cancelled ? "설치를 중단했습니다. 이미 설치된 항목은 유지됩니다." :
                    !completed ? SetupCore.Failure(result) : dryRun ? "미리보기 완료 — 실제 설치는 하지 않았습니다." :
                    build.Checked ? "설치가 완료되었습니다. 실행하기를 누르면 이 창은 닫힙니다." : "개발 환경 준비가 완료되었습니다. 프로젝트 폴더에서 just dev로 실행하세요.";
                if (!completed) ToggleLog(true);
            }
            catch (Exception error) { meter.Finish(false); status.Text = "설치를 완료하지 못했습니다."; RecordError(error); ToggleLog(true); }
            finally {
                running = false; cancelRequested = false;
                if (cancelFile != null) try { File.Delete(cancelFile); } catch (IOException) { } catch (UnauthorizedAccessException) { }
                cancelFile = null; ShowPage(SetupPage.Finished);
            }
        }
        void RecordError(Exception error)
        {
            string text = Environment.NewLine + error + Environment.NewLine;
            log.AppendText(text);
            if (logPath == null) return;
            try { File.AppendAllText(logPath, text, new UTF8Encoding(false)); }
            catch (Exception logError) { log.AppendText("오류 로그 저장 실패: " + logError.Message + Environment.NewLine); }
        }
        void Open(string path)
        {
            try { if (path != null) using (var process = Process.Start(new ProcessStartInfo(path) { UseShellExecute = true })) { } }
            catch (Exception error) { MessageBox.Show(this, error.Message, Text); }
        }
        protected override void Dispose(bool disposing)
        {
            if (disposing) { timer.Dispose(); clock.Stop(); }
            base.Dispose(disposing);
        }
    }

    internal static class Program
    {
        [STAThread]
        static int Main(string[] args)
        {
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            try {
                string root = SetupCore.ValidateRoot(AppDomain.CurrentDomain.BaseDirectory);
                string identity = System.Security.Principal.WindowsIdentity.GetCurrent().User.Value; bool owner;
                using (var mutex = new Mutex(true, "Local\\NHFutures-Setup-" + identity, out owner)) {
                    if (!owner) { MessageBox.Show("이미 설치 프로그램이 실행 중입니다. 기존 창에서 진행해 주세요.", "NH FUTURES API 설치"); return 2; }
                    try { Application.Run(new SetupForm(root)); } finally { mutex.ReleaseMutex(); }
                }
                return 0;
            } catch (Exception error) { MessageBox.Show(error.Message, "NH FUTURES API 설치"); return 1; }
        }
    }
}

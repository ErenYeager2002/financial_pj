using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Windows.Forms;

internal sealed class FinancialPlatformLauncherForm : Form
{
    private readonly string projectRoot;
    private readonly Button startButton;
    private readonly Button stopButton;
    private readonly Button openButton;
    private readonly CheckBox tasksCheckBox;
    private readonly CheckBox lanCheckBox;
    private readonly TextBox lanInterfaceTextBox;
    private readonly CheckBox openAfterStartCheckBox;
    private readonly Label statusLabel;
    private readonly ProgressBar progressBar;
    private readonly TextBox outputBox;
    private Process activeProcess;

    internal FinancialPlatformLauncherForm(string projectRoot)
    {
        this.projectRoot = projectRoot;

        Text = "财务 Skill 平台启动器";
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(680, 590);
        Size = new Size(760, 650);
        Font = new Font("Microsoft YaHei UI", 10F, FontStyle.Regular, GraphicsUnit.Point);
        BackColor = Color.FromArgb(247, 248, 250);
        FormBorderStyle = FormBorderStyle.Sizable;

        var titleLabel = new Label();
        titleLabel.Text = "财务 Skill 平台";
        titleLabel.Font = new Font(Font.FontFamily, 18F, FontStyle.Bold);
        titleLabel.AutoSize = true;
        titleLabel.Location = new Point(28, 24);

        var descriptionLabel = new Label();
        descriptionLabel.Text = "启动本机开发前端和 Docker 开发后端，不读取生产数据。";
        descriptionLabel.AutoSize = true;
        descriptionLabel.ForeColor = Color.FromArgb(80, 86, 96);
        descriptionLabel.Location = new Point(31, 67);

        tasksCheckBox = new CheckBox();
        tasksCheckBox.Text = "同时启动任务 Worker（执行任务时使用）";
        tasksCheckBox.AutoSize = true;
        tasksCheckBox.Location = new Point(32, 112);

        lanCheckBox = new CheckBox();
        lanCheckBox.Text = "启用 LAN 开发模式（局域网设备可访问）";
        lanCheckBox.Checked = true;
        lanCheckBox.AutoSize = true;
        lanCheckBox.Location = new Point(32, 145);

        var lanInterfaceLabel = new Label();
        lanInterfaceLabel.Text = "LAN 网卡名称：";
        lanInterfaceLabel.AutoSize = true;
        lanInterfaceLabel.Location = new Point(53, 180);

        lanInterfaceTextBox = new TextBox();
        lanInterfaceTextBox.Text = "以太网";
        lanInterfaceTextBox.Location = new Point(174, 175);
        lanInterfaceTextBox.Size = new Size(230, 27);
        lanCheckBox.CheckedChanged += delegate
        {
            lanInterfaceTextBox.Enabled = lanCheckBox.Checked;
        };

        openAfterStartCheckBox = new CheckBox();
        openAfterStartCheckBox.Text = "启动完成后打开浏览器";
        openAfterStartCheckBox.Checked = true;
        openAfterStartCheckBox.AutoSize = true;
        openAfterStartCheckBox.Location = new Point(32, 218);

        startButton = CreateButton("启动平台", new Point(32, 258), new Size(150, 42));
        startButton.BackColor = Color.FromArgb(30, 92, 196);
        startButton.ForeColor = Color.White;
        startButton.FlatStyle = FlatStyle.Flat;
        startButton.FlatAppearance.BorderSize = 0;
        startButton.Click += delegate { StartPlatform(); };

        openButton = CreateButton("打开平台", new Point(194, 258), new Size(130, 42));
        openButton.Click += delegate { OpenPlatform(); };

        stopButton = CreateButton("停止平台", new Point(336, 258), new Size(130, 42));
        stopButton.Click += delegate { StopPlatform(); };

        statusLabel = new Label();
        statusLabel.Text = "准备就绪";
        statusLabel.AutoSize = true;
        statusLabel.ForeColor = Color.FromArgb(70, 76, 86);
        statusLabel.Location = new Point(32, 322);

        progressBar = new ProgressBar();
        progressBar.Location = new Point(32, 350);
        progressBar.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
        progressBar.Size = new Size(ClientSize.Width - 64, 7);
        progressBar.Style = ProgressBarStyle.Continuous;

        outputBox = new TextBox();
        outputBox.Location = new Point(32, 376);
        outputBox.Size = new Size(ClientSize.Width - 64, ClientSize.Height - 408);
        outputBox.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right;
        outputBox.Multiline = true;
        outputBox.ReadOnly = true;
        outputBox.ScrollBars = ScrollBars.Vertical;
        outputBox.BackColor = Color.White;
        outputBox.Font = new Font("Consolas", 9F);
        outputBox.Text = "项目目录：" + projectRoot + Environment.NewLine;

        Controls.Add(titleLabel);
        Controls.Add(descriptionLabel);
        Controls.Add(tasksCheckBox);
        Controls.Add(lanCheckBox);
        Controls.Add(lanInterfaceLabel);
        Controls.Add(lanInterfaceTextBox);
        Controls.Add(openAfterStartCheckBox);
        Controls.Add(startButton);
        Controls.Add(openButton);
        Controls.Add(stopButton);
        Controls.Add(statusLabel);
        Controls.Add(progressBar);
        Controls.Add(outputBox);

        FormClosing += delegate(object sender, FormClosingEventArgs eventArgs)
        {
            if (activeProcess != null && !activeProcess.HasExited)
            {
                eventArgs.Cancel = true;
                MessageBox.Show(this, "当前操作尚未完成，请等待后再关闭启动器。", Text,
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
        };
    }

    private static Button CreateButton(string text, Point location, Size size)
    {
        var button = new Button();
        button.Text = text;
        button.Location = location;
        button.Size = size;
        button.Cursor = Cursors.Hand;
        return button;
    }

    private void StartPlatform()
    {
        string arguments = "-NoProfile -ExecutionPolicy Bypass -File " +
            QuoteArgument(Path.Combine(projectRoot, "scripts", "dev.ps1"));
        if (tasksCheckBox.Checked)
        {
            arguments += " -Mode Tasks";
        }
        if (lanCheckBox.Checked)
        {
            string interfaceAlias = lanInterfaceTextBox.Text.Trim();
            if (String.IsNullOrWhiteSpace(interfaceAlias))
            {
                MessageBox.Show(this, "启用 LAN 开发模式时必须填写网卡名称。", Text,
                    MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            arguments += " -Lan -LanInterfaceAlias " + QuoteArgument(interfaceAlias);
        }
        RunPowerShell(arguments, "正在启动平台，请稍候……", true);
    }

    private void StopPlatform()
    {
        string arguments = "-NoProfile -ExecutionPolicy Bypass -File " +
            QuoteArgument(Path.Combine(projectRoot, "scripts", "dev-stop.ps1"));
        RunPowerShell(arguments, "正在停止平台……", false);
    }

    private void RunPowerShell(string arguments, string runningText, bool openWhenFinished)
    {
        if (activeProcess != null && !activeProcess.HasExited)
        {
            MessageBox.Show(this, "启动器正在执行操作，请等待当前操作完成。", Text,
                MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }

        try
        {
            outputBox.Clear();
            AppendOutput("项目目录：" + projectRoot);
            SetBusy(true, runningText);

            var startInfo = new ProcessStartInfo();
            startInfo.FileName = FindPowerShell();
            startInfo.Arguments = arguments;
            startInfo.WorkingDirectory = projectRoot;
            startInfo.UseShellExecute = false;
            startInfo.CreateNoWindow = true;
            startInfo.RedirectStandardOutput = true;
            startInfo.RedirectStandardError = true;
            startInfo.StandardOutputEncoding = Encoding.UTF8;
            startInfo.StandardErrorEncoding = Encoding.UTF8;

            activeProcess = new Process();
            activeProcess.StartInfo = startInfo;
            activeProcess.EnableRaisingEvents = true;
            activeProcess.OutputDataReceived += delegate(object sender, DataReceivedEventArgs eventArgs)
            {
                if (eventArgs.Data != null) AppendOutput(eventArgs.Data);
            };
            activeProcess.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs eventArgs)
            {
                if (eventArgs.Data != null) AppendOutput(eventArgs.Data);
            };
            activeProcess.Exited += delegate(object sender, EventArgs eventArgs)
            {
                int exitCode = activeProcess.ExitCode;
                BeginInvoke((MethodInvoker)delegate
                {
                    SetBusy(false, exitCode == 0 ? "操作完成" : "操作失败，请查看下方信息");
                    statusLabel.ForeColor = exitCode == 0
                        ? Color.FromArgb(21, 128, 61)
                        : Color.FromArgb(185, 28, 28);
                    if (exitCode == 0 && openWhenFinished && openAfterStartCheckBox.Checked)
                    {
                        OpenPlatform();
                    }
                });
            };

            activeProcess.Start();
            activeProcess.BeginOutputReadLine();
            activeProcess.BeginErrorReadLine();
        }
        catch (Exception exception)
        {
            SetBusy(false, "无法执行操作");
            statusLabel.ForeColor = Color.FromArgb(185, 28, 28);
            AppendOutput(exception.Message);
        }
    }

    private void SetBusy(bool busy, string status)
    {
        startButton.Enabled = !busy;
        stopButton.Enabled = !busy;
        tasksCheckBox.Enabled = !busy;
        lanCheckBox.Enabled = !busy;
        lanInterfaceTextBox.Enabled = !busy && lanCheckBox.Checked;
        statusLabel.Text = status;
        if (busy)
        {
            statusLabel.ForeColor = Color.FromArgb(30, 92, 196);
            progressBar.Style = ProgressBarStyle.Marquee;
            progressBar.MarqueeAnimationSpeed = 25;
        }
        else
        {
            progressBar.MarqueeAnimationSpeed = 0;
            progressBar.Style = ProgressBarStyle.Continuous;
            progressBar.Value = 0;
        }
    }

    private void AppendOutput(string line)
    {
        if (InvokeRequired)
        {
            BeginInvoke((MethodInvoker)delegate { AppendOutput(line); });
            return;
        }
        outputBox.AppendText(line + Environment.NewLine);
        outputBox.SelectionStart = outputBox.TextLength;
        outputBox.ScrollToCaret();
    }

    private void OpenPlatform()
    {
        try
        {
            Process.Start(new ProcessStartInfo("http://localhost:3000") { UseShellExecute = true });
        }
        catch (Exception exception)
        {
            MessageBox.Show(this, exception.Message, "无法打开浏览器",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private static string FindPowerShell()
    {
        string programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        string powerShellRoot = Path.Combine(programFiles, "PowerShell");
        if (Directory.Exists(powerShellRoot))
        {
            string[] versionDirectories = Directory.GetDirectories(powerShellRoot);
            string[] candidates = Array.FindAll(
                Array.ConvertAll(versionDirectories, delegate(string directory)
                {
                    return Path.Combine(directory, "pwsh.exe");
                }),
                File.Exists);
            if (candidates.Length > 0)
            {
                Array.Sort(candidates, StringComparer.OrdinalIgnoreCase);
                return candidates[candidates.Length - 1];
            }
        }

        string pathPowerShell = FindExecutableOnPath("pwsh.exe");
        if (!String.IsNullOrWhiteSpace(pathPowerShell)) return pathPowerShell;

        throw new FileNotFoundException(
            "未找到 PowerShell 7（pwsh.exe）。请安装 PowerShell 7 后重新启动平台。"
        );
    }

    private static string FindExecutableOnPath(string fileName)
    {
        string pathValue = Environment.GetEnvironmentVariable("PATH") ?? String.Empty;
        foreach (string rawDirectory in pathValue.Split(Path.PathSeparator))
        {
            string directory = rawDirectory.Trim().Trim('"');
            if (String.IsNullOrWhiteSpace(directory)) continue;
            try
            {
                string candidate = Path.Combine(directory, fileName);
                if (File.Exists(candidate)) return candidate;
            }
            catch (ArgumentException)
            {
            }
            catch (NotSupportedException)
            {
            }
        }
        return null;
    }

    private static string QuoteArgument(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }
}

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        try
        {
            string projectRoot = FindProjectRoot(AppDomain.CurrentDomain.BaseDirectory);
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new FinancialPlatformLauncherForm(projectRoot));
        }
        catch (Exception exception)
        {
            MessageBox.Show(exception.Message, "财务 Skill 平台启动器",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private static string FindProjectRoot(string startDirectory)
    {
        string configuredRoot = Environment.GetEnvironmentVariable("FINANCIAL_PLATFORM_ROOT");
        if (!String.IsNullOrWhiteSpace(configuredRoot) && IsProjectRoot(configuredRoot))
        {
            return Path.GetFullPath(configuredRoot);
        }

        DirectoryInfo directory = new DirectoryInfo(startDirectory);
        while (directory != null)
        {
            if (IsProjectRoot(directory.FullName)) return directory.FullName;
            directory = directory.Parent;
        }

        throw new InvalidOperationException(
            "找不到项目目录。请把启动器放在 financial_pj 项目目录中，或设置 FINANCIAL_PLATFORM_ROOT。");
    }

    private static bool IsProjectRoot(string path)
    {
        return Directory.Exists(path) &&
            File.Exists(Path.Combine(path, "scripts", "dev.ps1")) &&
            File.Exists(Path.Combine(path, "scripts", "dev-stop.ps1")) &&
            File.Exists(Path.Combine(path, "CONTEXT.md"));
    }
}

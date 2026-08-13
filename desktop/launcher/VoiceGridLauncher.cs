using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

internal static class VoiceGridLauncher
{
    private const string ProductName = "\u58f0\u683c VoiceGrid";
    private const string HeadlessVariable = "VOICEGRID_LAUNCHER_HEADLESS";

    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int MessageBox(IntPtr owner, string text, string caption, uint type);

    [STAThread]
    private static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        bool validateOnly = Array.IndexOf(args, "--validate-only") >= 0;
        try
        {
            List<string> missing = FindMissingFiles(root);
            if (missing.Count > 0)
            {
                string detail = "\u542f\u52a8\u5668\u627e\u4e0d\u5230\u5fc5\u9700\u7684\u7a0b\u5e8f\u6587\u4ef6\uff1a" + Environment.NewLine + Environment.NewLine
                    + string.Join(Environment.NewLine, missing.ToArray()) + Environment.NewLine + Environment.NewLine
                    + "\u8bf7\u4e0d\u8981\u5355\u72ec\u590d\u5236 EXE\uff1b\u5982\u9700\u653e\u5230\u684c\u9762\uff0c\u8bf7\u4e3a\u9879\u76ee\u6839\u76ee\u5f55\u4e2d\u7684 EXE \u521b\u5efa\u5feb\u6377\u65b9\u5f0f\u3002";
                return Fail(root, 2, "Missing required files: " + string.Join(", ", missing.ToArray()), detail);
            }

            if (validateOnly)
            {
                return 0;
            }

            string pythonw = Path.Combine(root, ".venv", "Scripts", "pythonw.exe");
            ProcessStartInfo startInfo = new ProcessStartInfo
            {
                FileName = pythonw,
                Arguments = "-m desktop.host",
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            };
            Process process = Process.Start(startInfo);
            if (process == null)
            {
                return Fail(root, 3, "Process.Start returned null.", "\u65e0\u6cd5\u521b\u5efa\u58f0\u683c VoiceGrid \u684c\u9762\u8fdb\u7a0b\u3002");
            }
            process.Dispose();
            return 0;
        }
        catch (Exception error)
        {
            return Fail(root, 3, error.ToString(), "\u58f0\u683c VoiceGrid \u542f\u52a8\u5931\u8d25\u3002" + Environment.NewLine + Environment.NewLine + error.Message);
        }
    }

    private static List<string> FindMissingFiles(string root)
    {
        string[] relativePaths =
        {
            Path.Combine(".venv", "Scripts", "pythonw.exe"),
            Path.Combine("desktop", "host.py"),
            Path.Combine("desktop", "frontend", "dist", "index.html")
        };
        List<string> missing = new List<string>();
        foreach (string relativePath in relativePaths)
        {
            if (!File.Exists(Path.Combine(root, relativePath)))
            {
                missing.Add(relativePath);
            }
        }
        return missing;
    }

    private static int Fail(string root, int exitCode, string logDetail, string userMessage)
    {
        TryWriteLog(root, "ERROR " + logDetail);
        if (!string.Equals(Environment.GetEnvironmentVariable(HeadlessVariable), "1", StringComparison.Ordinal))
        {
            MessageBox(IntPtr.Zero, userMessage + Environment.NewLine + Environment.NewLine
                + "\u8be6\u7ec6\u4fe1\u606f\uff1alogs\\launcher.log", ProductName, 0x10U);
        }
        return exitCode;
    }

    private static void TryWriteLog(string root, string message)
    {
        try
        {
            string logs = Path.Combine(root, "logs");
            Directory.CreateDirectory(logs);
            string line = "[" + DateTime.Now.ToString("yyyy-MM-ddTHH:mm:ss.fff") + "] " + message + Environment.NewLine;
            File.AppendAllText(Path.Combine(logs, "launcher.log"), line, new UTF8Encoding(false));
        }
        catch
        {
            // A native error dialog remains available when logging is impossible.
        }
    }
}

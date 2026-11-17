using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

internal static class TrustedWindowCaptureHelper
{
    [StructLayout(LayoutKind.Sequential)]
    private struct RECT { public int Left, Top, Right, Bottom; }

    [DllImport("user32.dll")]
    private static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);

    [DllImport("user32.dll")]
    private static extern bool PrintWindow(IntPtr hwnd, IntPtr hdcBlt, uint nFlags);

    private static string Escape(string value)
    {
        if (value == null) return "null";
        StringBuilder output = new StringBuilder("\"");
        foreach (char ch in value)
        {
            if (ch == '\\') output.Append("\\\\");
            else if (ch == '"') output.Append("\\\"");
            else if (ch == '\n') output.Append("\\n");
            else if (ch == '\r') output.Append("\\r");
            else if (ch == '\t') output.Append("\\t");
            else if (ch < 32) output.Append("\\u" + ((int)ch).ToString("x4"));
            else output.Append(ch);
        }
        return output.Append('"').ToString();
    }

    private static string Value(string[] args, string name)
    {
        for (int i = 0; i + 1 < args.Length; i += 2)
            if (String.Equals(args[i], name, StringComparison.Ordinal))
                return args[i + 1];
        throw new ArgumentException("missing " + name);
    }

    public static int Main(string[] args)
    {
        try
        {
            if (args.Length != 6) throw new ArgumentException("three paired arguments required");
            int processId = Int32.Parse(Value(args, "--process-id"));
            string artifact = Path.GetFullPath(Value(args, "--artifact"));
            string output = Path.GetFullPath(Value(args, "--output"));
            if (!String.Equals(Path.GetExtension(output), ".png", StringComparison.OrdinalIgnoreCase))
                throw new ArgumentException("PNG output required");

            Process process = Process.GetProcessById(processId);
            string actual = Path.GetFullPath(process.MainModule.FileName);
            if (!String.Equals(actual, artifact, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("process artifact mismatch");
            IntPtr hwnd = process.MainWindowHandle;
            if (hwnd == IntPtr.Zero) throw new InvalidOperationException("main window unavailable");

            RECT rect;
            if (!GetWindowRect(hwnd, out rect)) throw new InvalidOperationException("window bounds unavailable");
            int width = rect.Right - rect.Left;
            int height = rect.Bottom - rect.Top;
            if (width < 100 || height < 100 || width > 10000 || height > 10000)
                throw new InvalidOperationException("unsafe window dimensions");

            Directory.CreateDirectory(Path.GetDirectoryName(output));
            using (Bitmap bitmap = new Bitmap(width, height, PixelFormat.Format32bppArgb))
            using (Graphics graphics = Graphics.FromImage(bitmap))
            {
                IntPtr hdc = graphics.GetHdc();
                bool ok;
                try { ok = PrintWindow(hwnd, hdc, 2); }
                finally { graphics.ReleaseHdc(hdc); }
                if (!ok) throw new InvalidOperationException("PrintWindow failed");
                bitmap.Save(output, ImageFormat.Png);
            }
            FileInfo info = new FileInfo(output);
            if (!info.Exists || info.Length <= 0 || info.Length > 25L * 1024L * 1024L)
                throw new InvalidOperationException("captured PNG invalid");
            Console.OutputEncoding = Encoding.UTF8;
            Console.WriteLine("{\"status\":\"WINDOW_CAPTURE_PASS\",\"process_id\":" +
                processId.ToString() + ",\"width\":" + width.ToString() +
                ",\"height\":" + height.ToString() + ",\"output\":" + Escape(output) + "}");
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.GetType().Name + ": " + error.Message);
            return 2;
        }
    }
}

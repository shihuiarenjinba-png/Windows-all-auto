using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Automation;

internal static class TrustedUiaHelper
{
    private static readonly Dictionary<string, ControlType> ControlTypes =
        new Dictionary<string, ControlType>(StringComparer.Ordinal)
        {
            { "Button", ControlType.Button }, { "Edit", ControlType.Edit },
            { "Text", ControlType.Text }, { "CheckBox", ControlType.CheckBox },
            { "ComboBox", ControlType.ComboBox }, { "ListItem", ControlType.ListItem },
            { "TabItem", ControlType.TabItem }, { "Document", ControlType.Document },
            { "Group", ControlType.Group }, { "Pane", ControlType.Pane },
        };

    private static string JsonEscape(string value)
    {
        if (value == null) return "null";
        StringBuilder result = new StringBuilder("\"");
        foreach (char ch in value)
        {
            switch (ch)
            {
                case '\\': result.Append("\\\\"); break;
                case '"': result.Append("\\\""); break;
                case '\n': result.Append("\\n"); break;
                case '\r': result.Append("\\r"); break;
                case '\t': result.Append("\\t"); break;
                default:
                    if (ch < 32) result.Append("\\u" + ((int)ch).ToString("x4"));
                    else result.Append(ch);
                    break;
            }
        }
        return result.Append('"').ToString();
    }

    private static Dictionary<string, string> ParseArgs(string[] args)
    {
        Dictionary<string, string> result = new Dictionary<string, string>(StringComparer.Ordinal);
        if (args.Length % 2 != 0) throw new ArgumentException("paired arguments required");
        for (int index = 0; index < args.Length; index += 2)
        {
            if (!args[index].StartsWith("--", StringComparison.Ordinal))
                throw new ArgumentException("invalid argument name");
            result.Add(args[index].Substring(2), args[index + 1]);
        }
        return result;
    }

    private static AutomationElement UniqueWindow(int processId, string titleContains)
    {
        AutomationElementCollection items = AutomationElement.RootElement.FindAll(
            TreeScope.Children,
            new PropertyCondition(AutomationElement.ProcessIdProperty, processId));
        List<AutomationElement> matches = new List<AutomationElement>();
        foreach (AutomationElement item in items)
        {
            string name = item.Current.Name ?? "";
            if (name.IndexOf(titleContains, StringComparison.OrdinalIgnoreCase) >= 0)
                matches.Add(item);
        }
        if (matches.Count != 1) throw new InvalidOperationException("window match count " + matches.Count);
        return matches[0];
    }

    private static AutomationElement DefaultWindow(int processId)
    {
        AutomationElementCollection items = AutomationElement.RootElement.FindAll(
            TreeScope.Children,
            new PropertyCondition(AutomationElement.ProcessIdProperty, processId));
        if (items.Count != 1) throw new InvalidOperationException("process window count " + items.Count);
        return items[0];
    }

    private static AutomationElement UniqueControl(
        AutomationElement window, string name, string controlType)
    {
        List<Condition> conditions = new List<Condition>();
        conditions.Add(new PropertyCondition(AutomationElement.NameProperty, name));
        if (!String.IsNullOrEmpty(controlType))
        {
            ControlType value;
            if (!ControlTypes.TryGetValue(controlType, out value))
                throw new ArgumentException("unsupported control type");
            conditions.Add(new PropertyCondition(AutomationElement.ControlTypeProperty, value));
        }
        Condition condition = conditions.Count == 1
            ? conditions[0] : new AndCondition(conditions.ToArray());
        AutomationElementCollection matches = window.FindAll(TreeScope.Descendants, condition);
        if (matches.Count != 1) throw new InvalidOperationException("control match count " + matches.Count);
        return matches[0];
    }

    public static int Main(string[] args)
    {
        try
        {
            Dictionary<string, string> options = ParseArgs(args);
            string action = options["action"];
            int processId = Int32.Parse(options["process-id"]);
            string artifact = Path.GetFullPath(options["artifact"]);
            Process process = Process.GetProcessById(processId);
            string actual = Path.GetFullPath(process.MainModule.FileName);
            if (!String.Equals(actual, artifact, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("process artifact mismatch");
            JavaScriptSerializer serializer = new JavaScriptSerializer();
            Dictionary<string, object> parameters =
                serializer.Deserialize<Dictionary<string, object>>(options["params-json"]);
            AutomationElement window;
            AutomationElement control = null;
            string observed = null;
            if (action == "UIA_FIND_WINDOW")
            {
                window = UniqueWindow(processId, (string)parameters["title_contains"]);
                observed = window.Current.Name;
            }
            else
            {
                window = DefaultWindow(processId);
                string controlType = parameters.ContainsKey("control_type")
                    ? (string)parameters["control_type"] : "";
                control = UniqueControl(window, (string)parameters["name"], controlType);
                observed = control.Current.Name;
                if (action == "UIA_INVOKE")
                {
                    InvokePattern pattern = control.GetCurrentPattern(InvokePattern.Pattern) as InvokePattern;
                    if (pattern == null) throw new InvalidOperationException("invoke pattern unavailable");
                    pattern.Invoke();
                }
                else if (action == "UIA_READ_TEXT")
                {
                    object candidate;
                    if (control.TryGetCurrentPattern(ValuePattern.Pattern, out candidate))
                        observed = ((ValuePattern)candidate).Current.Value;
                }
                else if (action == "UIA_SET_TEXT")
                {
                    ValuePattern pattern = control.GetCurrentPattern(ValuePattern.Pattern) as ValuePattern;
                    if (pattern == null || pattern.Current.IsReadOnly)
                        throw new InvalidOperationException("settable value pattern unavailable");
                    pattern.SetValue((string)parameters["value"]);
                    observed = (string)parameters["value"];
                }
                else if (action != "UIA_FIND_CONTROL")
                {
                    throw new ArgumentException("unsupported action");
                }
            }
            Console.OutputEncoding = Encoding.UTF8;
            Console.WriteLine("{\"status\":\"UIA_PASS\",\"action\":" + JsonEscape(action) +
                ",\"process_id\":" + processId.ToString() + ",\"observed\":" +
                JsonEscape(observed ?? "") + "}");
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.GetType().Name + ": " + error.Message);
            return 2;
        }
    }
}

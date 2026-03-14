<%@ WebHandler Language="C#" Class="SettingsHandler" %>

using System;
using System.Collections.Generic;
using System.IO;
using System.Web;
using System.Web.Script.Serialization;

public class SettingsHandler : IHttpHandler
{
    private const string DataPath = "~/App_Data/settings.json";

    public bool IsReusable => false;

    public void ProcessRequest(HttpContext context)
    {
        context.Response.ContentType = "application/json";

        try
        {
            var method = context.Request.HttpMethod;

            if (method == "GET")
            {
                WriteJson(context, LoadSettings(context));
                return;
            }

            if (method == "POST")
            {
                var serializer = new JavaScriptSerializer();
                using (var reader = new StreamReader(context.Request.InputStream))
                {
                    var payload = reader.ReadToEnd();
                    var settings = serializer.Deserialize<Dictionary<string, object>>(payload)
                                   ?? new Dictionary<string, object>();

                    SaveSettings(context, settings);
                    WriteJson(context, new { success = true });
                    return;
                }
            }

            context.Response.StatusCode = 405;
            WriteJson(context, new { success = false, message = "Method Not Allowed" });
        }
        catch (Exception ex)
        {
            context.Response.StatusCode = 500;
            WriteJson(context, new { success = false, message = ex.Message, stack = ex.StackTrace });
        }
    }

    private Dictionary<string, object> LoadSettings(HttpContext context)
    {
        var path = context.Server.MapPath(DataPath);
        if (!File.Exists(path))
        {
            return new Dictionary<string, object>();
        }

        var json = File.ReadAllText(path);
        if (string.IsNullOrWhiteSpace(json))
        {
            return new Dictionary<string, object>();
        }

        var serializer = new JavaScriptSerializer();
        return serializer.Deserialize<Dictionary<string, object>>(json)
               ?? new Dictionary<string, object>();
    }

    private void SaveSettings(HttpContext context, Dictionary<string, object> settings)
    {
        var path = context.Server.MapPath(DataPath);
        var directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(directory) && !Directory.Exists(directory))
        {
            Directory.CreateDirectory(directory);
        }

        if (settings.ContainsKey("backgroundUrl") && settings["backgroundUrl"] != null)
        {
            var backgroundUrl = settings["backgroundUrl"].ToString();
            settings["backgroundUrl"] = NormalizePath(backgroundUrl);
        }

        var serializer = new JavaScriptSerializer();
        var json = serializer.Serialize(settings);
        File.WriteAllText(path, json);
    }

    private string NormalizePath(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return string.Empty;
        }

        var raw = value.Trim();
        if (raw.StartsWith("http://", StringComparison.OrdinalIgnoreCase) ||
            raw.StartsWith("https://", StringComparison.OrdinalIgnoreCase) ||
            raw.StartsWith("/uploads/", StringComparison.OrdinalIgnoreCase) ||
            raw.StartsWith("/assets/images/", StringComparison.OrdinalIgnoreCase))
        {
            return raw;
        }

        if (raw.StartsWith("uploads/", StringComparison.OrdinalIgnoreCase) ||
            raw.StartsWith("assets/images/", StringComparison.OrdinalIgnoreCase))
        {
            return "/" + raw;
        }

        return "/assets/images/" + raw.TrimStart('/');
    }

    private void WriteJson(HttpContext context, object data)
    {
        var serializer = new JavaScriptSerializer();
        context.Response.Write(serializer.Serialize(data));
    }
}

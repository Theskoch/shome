<%@ WebHandler Language="C#" Class="ServicesHandler" %>

using System;
using System.Collections.Generic;
using System.IO;
using System.Web;
using System.Web.Script.Serialization;

public class ServicesHandler : IHttpHandler
{
    private const string DataPath = "~/App_Data/services.json";

    public bool IsReusable => false;

    public void ProcessRequest(HttpContext context)
    {
        context.Response.ContentType = "application/json";
        try
        {
            var method = context.Request.HttpMethod;

            if (method == "GET")
            {
                WriteJson(context, LoadServices(context));
                return;
            }

            if (method == "POST")
            {
                var serializer = new JavaScriptSerializer();
                using (var reader = new StreamReader(context.Request.InputStream))
                {
                    var payload = reader.ReadToEnd();
                    var services = serializer.Deserialize<List<ServiceItem>>(payload) ?? new List<ServiceItem>();
                    SaveServices(context, services);
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

    private List<ServiceItem> LoadServices(HttpContext context)
    {
        var path = context.Server.MapPath(DataPath);
        if (!File.Exists(path))
        {
            return new List<ServiceItem>();
        }

        var json = File.ReadAllText(path);
        if (string.IsNullOrWhiteSpace(json))
        {
            return new List<ServiceItem>();
        }

        var serializer = new JavaScriptSerializer();
        return serializer.Deserialize<List<ServiceItem>>(json) ?? new List<ServiceItem>();
    }

    private void SaveServices(HttpContext context, List<ServiceItem> services)
    {
        var path = context.Server.MapPath(DataPath);
        var directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(directory) && !Directory.Exists(directory))
        {
            Directory.CreateDirectory(directory);
        }

        var serializer = new JavaScriptSerializer();
        var json = serializer.Serialize(services);
        File.WriteAllText(path, json);
    }

    private void WriteJson(HttpContext context, object data)
    {
        var serializer = new JavaScriptSerializer();
        context.Response.Write(serializer.Serialize(data));
    }

    public class ServiceItem
    {
        public string Id { get; set; }
        public string Title { get; set; }
        public string Url { get; set; }
        public string Icon { get; set; }
        public bool IsModal { get; set; }
    }
}
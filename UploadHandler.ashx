<%@ WebHandler Language="C#" Class="UploadHandler" %>

using System;
using System.Collections.Generic;
using System.IO;
using System.Web;
using System.Web.Script.Serialization;

public class UploadHandler : IHttpHandler
{
    private const string UploadFolder = "~/uploads";

    public bool IsReusable => false;

    public void ProcessRequest(HttpContext context)
    {
        context.Response.ContentType = "application/json";

        try
        {
            if (context.Request.HttpMethod != "POST")
            {
                context.Response.StatusCode = 405;
                WriteJson(context, new { success = false, message = "Method Not Allowed" });
                return;
            }

            var file = context.Request.Files["file"];
            if (file == null || file.ContentLength == 0)
            {
                context.Response.StatusCode = 400;
                WriteJson(context, new { success = false, message = "Файл не найден" });
                return;
            }

            if (!IsAllowed(file))
            {
                context.Response.StatusCode = 400;
                WriteJson(context, new { success = false, message = "Недопустимый формат файла" });
                return;
            }

            var extension = Path.GetExtension(file.FileName)?.ToLowerInvariant() ?? string.Empty;
            if (string.IsNullOrWhiteSpace(extension))
            {
                extension = GuessExtension(file.ContentType);
            }

            var uploadPath = context.Server.MapPath(UploadFolder);
            if (!Directory.Exists(uploadPath))
            {
                Directory.CreateDirectory(uploadPath);
            }

            var fileName = $"{Guid.NewGuid():N}{extension}";
            var savedPath = Path.Combine(uploadPath, fileName);
            file.SaveAs(savedPath);

            var publicUrl = $"/uploads/{fileName}";
            WriteJson(context, new { success = true, url = publicUrl });
        }
        catch (Exception ex)
        {
            context.Response.StatusCode = 500;
            WriteJson(context, new { success = false, message = ex.Message, stack = ex.StackTrace });
        }
    }

    private void WriteJson(HttpContext context, object data)
    {
        var serializer = new JavaScriptSerializer();
        context.Response.Write(serializer.Serialize(data));
    }

    private bool IsAllowed(HttpPostedFile file)
    {
        var contentType = (file.ContentType ?? string.Empty).ToLowerInvariant();
        if (contentType.StartsWith("image/"))
        {
            return true;
        }

        // Fallback for clients that do not send proper MIME type
        var extension = Path.GetExtension(file.FileName);
        return !string.IsNullOrWhiteSpace(extension);
    }

    private string GuessExtension(string contentType)
    {
        var ctype = (contentType ?? string.Empty).ToLowerInvariant();
        var map = new Dictionary<string, string>
        {
            { "image/jpeg", ".jpg" },
            { "image/jpg", ".jpg" },
            { "image/png", ".png" },
            { "image/gif", ".gif" },
            { "image/webp", ".webp" },
            { "image/svg+xml", ".svg" },
            { "image/bmp", ".bmp" },
            { "image/x-icon", ".ico" },
            { "image/vnd.microsoft.icon", ".ico" },
            { "image/tiff", ".tiff" },
            { "image/avif", ".avif" },
            { "image/heic", ".heic" },
            { "image/heif", ".heif" }
        };

        if (map.ContainsKey(ctype))
        {
            return map[ctype];
        }

        return ".img";
    }
}
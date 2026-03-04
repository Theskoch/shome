<%@ WebHandler Language="C#" Class="UploadHandler" %>

using System;
using System.IO;
using System.Linq;
using System.Web;
using System.Web.Script.Serialization;

public class UploadHandler : IHttpHandler
{
    private const string UploadFolder = "~/uploads";
    private static readonly string[] AllowedExtensions = { ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp" };

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

            var extension = Path.GetExtension(file.FileName)?.ToLowerInvariant() ?? string.Empty;
            if (!AllowedExtensions.Contains(extension))
            {
                context.Response.StatusCode = 400;
                WriteJson(context, new { success = false, message = "Недопустимый формат файла" });
                return;
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
}
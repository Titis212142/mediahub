(function () {
  function getFingerprint() {
    var components = [];

    components.push(screen.width + "x" + screen.height);
    components.push(screen.colorDepth);
    components.push(new Date().getTimezoneOffset());
    components.push(navigator.language);
    components.push(navigator.platform);
    components.push(navigator.hardwareConcurrency || "unknown");
    components.push(navigator.deviceMemory || "unknown");

    try {
      var canvas = document.createElement("canvas");
      var ctx = canvas.getContext("2d");
      canvas.width = 200;
      canvas.height = 50;
      ctx.textBaseline = "top";
      ctx.font = "14px 'Arial'";
      ctx.fillStyle = "#f60";
      ctx.fillRect(0, 0, 200, 50);
      ctx.fillStyle = "#069";
      ctx.fillText("MediaHub.fp" + String.fromCharCode(55357, 56489), 2, 15);
      ctx.fillStyle = "rgba(102, 204, 0, 0.7)";
      ctx.fillText("MediaHub.fp" + String.fromCharCode(55357, 56489), 4, 17);
      components.push(canvas.toDataURL());
    } catch (e) {
      components.push("no-canvas");
    }

    try {
      var gl =
        document.createElement("canvas").getContext("webgl") ||
        document.createElement("canvas").getContext("experimental-webgl");
      if (gl) {
        var debugInfo = gl.getExtension("WEBGL_debug_renderer_info");
        if (debugInfo) {
          components.push(gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL));
          components.push(gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL));
        }
      }
    } catch (e) {
      components.push("no-webgl");
    }

    var raw = components.join("|||");
    return hashCode(raw);
  }

  function hashCode(str) {
    var hash = 0;
    for (var i = 0; i < str.length; i++) {
      var char = str.charCodeAt(i);
      hash = (hash << 5) - hash + char;
      hash |= 0;
    }
    var h2 = 0x811c9dc5;
    for (var i = 0; i < str.length; i++) {
      h2 ^= str.charCodeAt(i);
      h2 = Math.imul(h2, 0x01000193);
    }
    return (
      Math.abs(hash).toString(16).padStart(8, "0") +
      Math.abs(h2 >>> 0)
        .toString(16)
        .padStart(8, "0")
    );
  }

  var fp = getFingerprint();
  document.cookie =
    "device_fp=" + fp + ";path=/;max-age=31536000;SameSite=Lax";
})();

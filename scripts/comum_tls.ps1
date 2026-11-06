# Saude da producao na propria maquina, por HTTPS (issue #425). Usado pelo watchdog.ps1, pelo deploy.ps1 e pelo
# saude_local.ps1 (dot-source: . (Join-Path $PSScriptRoot "comum_tls.ps1")).
#
# O certificado da producao e' autoassinado e emitido para o nome da maquina, nao para "localhost" de forma
# confiavel na cadeia do Windows: o Invoke-WebRequest do PowerShell 5.1 recusaria https://localhost:<porta>. Em vez
# de desligar a verificacao (o que aceitaria qualquer certificado), o pedido aceita SO' o certificado da propria
# instalacao, comparando o thumbprint com o do <raiz>\segredos\tls\cert.pem. A validacao do certificado e' do PEDIDO
# (HttpWebRequest.ServerCertificateValidationCallback), nunca a callback global do processo (ServicePointManager), e so'
# vale para localhost/127.0.0.1: qualquer outro endereco e' recusado antes de sair. A unica coisa global que o pedido
# toca e' acrescentar TLS 1.2 aos protocolos do processo (o .NET Framework nao tem isso por pedido); nada e' tirado.
#
# A classe em C# so' e' compilada no primeiro pedido https (Add-Type chama o compilador): a producao em HTTP (-SemTls)
# continua so' com o Invoke-WebRequest de antes.
#
# Este arquivo fica so' com ASCII (sem BOM, o 5.1 le como ANSI e acento quebra o parse).

function Initialize-DashSaudeLocal {
    if ("DashSaudeLocal" -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Net;
using System.Net.Security;
using System.Security.Cryptography.X509Certificates;
using System.Text;

public class DashRespostaSaude {
    public int StatusCode;
    public string Content;
}

public static class DashSaudeLocal {
    public static DashRespostaSaude Pedir(string url, string thumbprint, int timeoutMs) {
        Uri uri = new Uri(url);
        if (!uri.IsLoopback) { throw new ArgumentException("A saude local so' fala com localhost: " + url); }
        if (uri.Scheme != Uri.UriSchemeHttps) { throw new ArgumentException("Endereco sem https: " + url); }
        if (String.IsNullOrEmpty(thumbprint)) { throw new ArgumentException("Thumbprint do certificado vazio."); }
        // O PowerShell 5.1 pode nascer so' com SSL3/TLS 1.0; o uvicorn exige TLS 1.2 ou mais.
        ServicePointManager.SecurityProtocol = ServicePointManager.SecurityProtocol | SecurityProtocolType.Tls12;
        HttpWebRequest pedido = (HttpWebRequest)WebRequest.Create(uri);
        pedido.Timeout = timeoutMs;
        pedido.ReadWriteTimeout = timeoutMs;
        pedido.Proxy = null;
        pedido.KeepAlive = false;
        string esperado = thumbprint;
        pedido.ServerCertificateValidationCallback = delegate (object remetente, X509Certificate cert, X509Chain cadeia, SslPolicyErrors erros) {
            if (cert == null) { return false; }
            X509Certificate2 c2 = new X509Certificate2(cert);
            return String.Equals(c2.Thumbprint, esperado, StringComparison.OrdinalIgnoreCase);
        };
        HttpWebResponse resposta;
        try {
            resposta = (HttpWebResponse)pedido.GetResponse();
        } catch (WebException ex) {
            // 4xx/5xx chegam como excecao com a resposta dentro; sem resposta (conexao, certificado errado) sobe.
            resposta = ex.Response as HttpWebResponse;
            if (resposta == null) { throw; }
        }
        using (resposta) {
            DashRespostaSaude r = new DashRespostaSaude();
            r.StatusCode = (int)resposta.StatusCode;
            using (StreamReader leitor = new StreamReader(resposta.GetResponseStream(), Encoding.UTF8)) {
                r.Content = leitor.ReadToEnd();
            }
            return r;
        }
    }
}
'@
}

# Thumbprint (SHA-1, como o Windows mostra) do certificado PEM da instalacao. O PEM e' lido aqui, sem depender de o
# X509Certificate2 do .NET aceitar o arquivo com cabecalho.
function Get-ThumbprintDoCertificado {
    param([Parameter(Mandatory = $true)][string]$Caminho)
    if (-not (Test-Path -LiteralPath $Caminho)) { throw "certificado do HTTPS nao encontrado em $Caminho" }
    $texto = [System.IO.File]::ReadAllText($Caminho)
    $m = [regex]::Match($texto, "-----BEGIN CERTIFICATE-----([A-Za-z0-9+/=\s]+)-----END CERTIFICATE-----")
    if (-not $m.Success) { throw "$Caminho nao tem um certificado PEM" }
    $der = [Convert]::FromBase64String(($m.Groups[1].Value -replace "\s", ""))
    $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 -ArgumentList (, $der)
    return $cert.Thumbprint
}

# GET na saude local. http:// (producao com -SemTls) vai pelo Invoke-WebRequest de sempre; https:// exige -Certificado
# e so' aceita o certificado desse arquivo. Devolve StatusCode e Content; falha de conexao ou certificado lanca.
function Invoke-SaudeLocal {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [string]$Certificado = "",
        # Ja' lido do -Certificado por quem chama (o watchdog le uma vez por execucao: arquivo que fique ilegivel no meio
        # nao vira "producao fora"). Vazio = ler do -Certificado aqui.
        [string]$Thumbprint = "",
        [int]$TimeoutSec = 12
    )
    if ($Url -like "http://*") {
        try {
            $r = Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSec -UseBasicParsing
            return [pscustomobject]@{ StatusCode = [int]$r.StatusCode; Content = [string]$r.Content }
        }
        catch [System.Net.WebException] {
            # 4xx/5xx (ex.: 503 com o banco fora) vem como excecao com a resposta dentro: devolver como no https.
            $resposta = $_.Exception.Response
            if ($null -eq $resposta) { throw }
            $leitor = New-Object System.IO.StreamReader -ArgumentList $resposta.GetResponseStream()
            try { $corpo = $leitor.ReadToEnd() } finally { $leitor.Dispose(); $resposta.Close() }
            return [pscustomobject]@{ StatusCode = [int]$resposta.StatusCode; Content = $corpo }
        }
    }
    Initialize-DashSaudeLocal
    if (-not $Thumbprint) {
        if (-not $Certificado) { throw "saude por https sem o caminho do certificado da instalacao" }
        $Thumbprint = Get-ThumbprintDoCertificado -Caminho $Certificado
    }
    $r = [DashSaudeLocal]::Pedir($Url, $Thumbprint, $TimeoutSec * 1000)
    return [pscustomobject]@{ StatusCode = $r.StatusCode; Content = $r.Content }
}

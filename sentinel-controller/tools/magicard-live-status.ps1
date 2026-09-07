param(
    [string]$PrinterHost = "10.1.1.108",
    [int]$Port = 9100,
    [int]$TimeoutMilliseconds = 5000
)

$ErrorActionPreference = "Stop"

function Get-Number($Values, [int]$Index) {
    if ($Index -ge $Values.Count) { return $null }
    $number = 0
    if ([int]::TryParse($Values[$Index], [ref]$number)) { return $number }
    return $null
}

$client = [System.Net.Sockets.TcpClient]::new()
try {
    $connect = $client.ConnectAsync($PrinterHost, $Port)
    if (-not $connect.Wait($TimeoutMilliseconds)) {
        throw "Timed out connecting to Magicard at ${PrinterHost}:${Port}."
    }

    $client.ReceiveTimeout = $TimeoutMilliseconds
    $client.SendTimeout = $TimeoutMilliseconds
    $stream = $client.GetStream()

    # Official Magicard information request used by its Linux CUPS driver.
    # This queries status only and contains no printable card data.
    [byte[]]$request = 0x01, 0x2c, 0x52, 0x45, 0x51, 0x2c, 0x49, 0x4e, 0x46, 0x2c, 0x1c, 0x03
    $stream.Write($request, 0, $request.Length)
    $stream.Flush()

    $buffer = [byte[]]::new(4096)
    $bytes = $stream.Read($buffer, 0, $buffer.Length)
    if ($bytes -le 0) {
        throw "Magicard accepted the connection but returned no status data."
    }

    $response = [System.Text.Encoding]::ASCII.GetString($buffer, 0, $bytes)
    $response = $response.Trim([char]0x00, [char]0x01, [char]0x03, [char]0x1c)
    if (-not $response.StartsWith("STA$$")) {
        throw "Unexpected Magicard response: $response"
    }

    $payload = $response.Substring(5).TrimStart(',', ':')
    $values = @($payload -split '[,:]')
    $shotsOnFilm = Get-Number $values 22
    $shotsUsed = Get-Number $values 23
    $remainingPercent = $null
    if ($null -ne $shotsOnFilm -and $null -ne $shotsUsed -and ($shotsOnFilm + $shotsUsed) -gt 0) {
        $remainingPercent = [math]::Round(($shotsOnFilm * 100.0) / ($shotsOnFilm + $shotsUsed))
    }

    [ordered]@{
        online = $true
        model = if ($values.Count -gt 1) { $values[1] } else { $null }
        serial = if ($values.Count -gt 3) { $values[3] } else { $null }
        printhead_serial = if ($values.Count -gt 4) { $values[4] } else { $null }
        firmware = if ($values.Count -gt 6) { $values[6] } else { $null }
        hand_feed = Get-Number $values 8
        total_cards_printed = Get-Number $values 9
        cards_printed_by_printhead = Get-Number $values 10
        cleans_since_shipped = Get-Number $values 12
        dye_panels_since_clean = Get-Number $values 13
        cards_since_clean = Get-Number $values 14
        cards_between_cleans = Get-Number $values 15
        major_error = Get-Number $values 19
        minor_error = Get-Number $values 20
        shots_on_film = $shotsOnFilm
        shots_used = $shotsUsed
        prints_remaining_percent = $remainingPercent
        dye_film_type = if ($values.Count -gt 24) { $values[24] } else { $null }
        checked_at = [DateTimeOffset]::UtcNow.ToString("o")
    } | ConvertTo-Json
}
finally {
    $client.Dispose()
}

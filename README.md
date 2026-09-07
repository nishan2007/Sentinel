# Sentinel WiFi Captive Portal

Static Cloudflare Pages project for a Sentinel-branded customer guest WiFi captive portal.

## Start Sentinel Locally

On macOS, double-click:

```text
Start Sentinel.command
```

That launcher creates the Python environment if needed, installs server dependencies, starts the Sentinel backend, and opens:

```text
http://localhost:8088/dashboard
```

From Terminal, you can run the same launcher with:

```bash
./start-sentinel.sh
```

To use a different port:

```bash
SENTINEL_PORT=8090 ./start-sentinel.sh
```

## Files

- `index.html` - Portal markup and form fields
- `styles.css` - Mobile-first Sentinel styling
- `script.js` - Query parameter parsing, validation, Supabase Edge Function submit, and redirect handling

## Configure the Supabase Edge Function URL

Open `script.js` and replace:

```js
https://YOUR_PROJECT_REF.supabase.co/functions/v1/wifi-captive-login
```

with your public Supabase Edge Function URL.

Do not put a Supabase service role key, private key, or any other secret in `script.js`. The service role key must only be used inside the Supabase Edge Function.

For a public captive portal, the Edge Function must allow unauthenticated browser requests. In Supabase, open the `wifi-captive-login` Edge Function settings and turn off JWT verification. If JWT verification stays enabled, the browser POST will fail with `401 Missing authorization header`.

## Upload to Cloudflare Pages

1. Create a new Cloudflare Pages project.
2. Connect a Git repository containing these files, or upload the folder directly through Cloudflare Pages.
3. Use these build settings:
   - Framework preset: `None`
   - Build command: leave blank
   - Build output directory: `/`
4. Deploy the project.
5. Copy the deployed Cloudflare Pages URL, such as:

```text
https://sentinel-wifi.pages.dev
```

## Router Captive Portal URL

Put the deployed Cloudflare Pages URL into the router or access point captive portal login page field.

Example:

```text
https://sentinel-wifi.pages.dev
```

If your router supports appending client/session values, configure it to pass the query parameters below.

## Router Query Parameters

The portal reads these URL query parameters on page load:

- `mac` - Customer device MAC address
- `ip` - Customer device IP address
- `location_id` - Store/location UUID
- `nasid` - Network access server ID
- `session_id` - Router or captive portal session ID
- `redirect_url` - URL to send the customer to after successful login

Example captive portal URL:

```text
https://sentinel-wifi.pages.dev/?mac={{client_mac}}&ip={{client_ip}}&location_id={{location_id}}&nasid={{nasid}}&session_id={{session_id}}&redirect_url=https%3A%2F%2Fwww.google.com
```

Use the variable syntax required by your router vendor.

The page uses public Supabase Storage image URLs for the Sentinel logos. If your router blocks external assets before login, add this host to the captive portal/walled-garden allow list:

```text
wbffhygkttoaaodjcvuh.supabase.co
```

## Submitted JSON Body

The frontend posts this JSON shape to the Supabase Edge Function:

```json
{
  "full_name": "Alex Morgan",
  "email": "alex@example.com",
  "phone": "(555) 123-4567",
  "accepted_terms": true,
  "mac_address": "00:11:22:33:44:55",
  "device_ip": "192.168.1.24",
  "location_id": "00000000-0000-0000-0000-000000000000",
  "nas_id": "store-router-1",
  "session_id": "abc123",
  "redirect_url": "https://www.google.com",
  "user_agent": "Customer browser user agent",
  "submitted_at": "2026-05-01T12:00:00.000Z"
}
```

If the request succeeds, the customer is redirected to `redirect_url`. If no `redirect_url` is present, the portal redirects to `https://www.google.com`.

## Sample Supabase SQL Table

```sql
create table public.wifi_sessions (
  id uuid primary key default gen_random_uuid(),
  full_name text,
  email text,
  phone text,
  mac_address text,
  device_ip text,
  location_id uuid null,
  nas_id text,
  session_id text,
  redirect_url text,
  user_agent text,
  accepted_terms boolean default false,
  status text default 'pending',
  created_at timestamptz default now(),
  expires_at timestamptz
);
```

## Optional Customer Account Creation

The portal already collects `full_name`, `email`, and `phone`, so the Supabase Edge Function can also create or reuse a row in `public.customer_accounts`.

To link WiFi sessions back to customer accounts, add this optional column:

```sql
alter table public.wifi_sessions
add column if not exists customer_id integer null
references public.customer_accounts (customer_id);

create index if not exists wifi_sessions_customer_id_idx
on public.wifi_sessions using btree (customer_id);
```

In the Edge Function, create or find the customer before inserting the WiFi session:

```ts
async function findOrCreateCustomer(supabase, payload) {
  const name = (payload.full_name || "").trim();
  const email = (payload.email || "").trim().toLowerCase();
  const phone = (payload.phone || "").trim();

  if (!name) {
    return null;
  }

  let existingCustomer = null;

  if (email) {
    const { data } = await supabase
      .from("customer_accounts")
      .select("customer_id")
      .eq("email", email)
      .maybeSingle();

    existingCustomer = data;
  }

  if (!existingCustomer && phone) {
    const { data } = await supabase
      .from("customer_accounts")
      .select("customer_id")
      .eq("phone", phone)
      .maybeSingle();

    existingCustomer = data;
  }

  if (existingCustomer) {
    return existingCustomer.customer_id;
  }

  const { data, error } = await supabase
    .from("customer_accounts")
    .insert({
      name,
      email: email || null,
      phone: phone || null,
      credit_limit: 0,
      current_balance: 0,
      is_active: true,
      is_business: false,
      account_notes: "Created from Sentinel WiFi captive portal"
    })
    .select("customer_id")
    .single();

  if (error) {
    throw error;
  }

  return data.customer_id;
}
```

Then call it before inserting into `wifi_sessions`:

```ts
const customerId = await findOrCreateCustomer(supabase, payload);
```

And include the returned ID in the WiFi session insert:

```ts
customer_id: customerId,
```

## Security Reminder

The Supabase service role key must only be used inside the Supabase Edge Function. Never expose it in `script.js`, `index.html`, Cloudflare Pages public files, or client-side environment variables.

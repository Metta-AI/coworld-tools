# AWS SSO Login on Mettaboxes (No-Browser Flow)

This doc explains how to log into AWS SSO **from inside a mettabox container** (metta0/1/2/etc) without leaking
credentials. It uses the AWS CLI v2 `--no-browser` flow and an SSH tunnel so the localhost callback can complete.

## When you need this

- `aws sts get-caller-identity --profile softmax` fails.
- `./install.sh` prints SSO refresh errors or says policy storage is local only.
- AWS SSO cache JSON is corrupted (JSONDecodeError).

## Preconditions

- You can SSH to the mettabox (`ssh metta@metta1`).
- You have access to the Softmax AWS SSO portal in your browser.

## Steps (recommended)

### 1) Start login inside the container

Run the login in the container (via mettabox CLI from your local dev machine):

```bash
uv run python devops/mettabox/cli.py exec metta1 -- /usr/local/bin/aws sso login --profile softmax --no-browser
```

This prints a URL with a **localhost callback** like:

```
https://oidc.us-east-1.amazonaws.com/authorize?...&redirect_uri=http%3A%2F%2F127.0.0.1%3A39945%2Foauth%2Fcallback...
```

Leave the command running while you complete the browser step.

### 2) Create a tunnel for the callback

From your laptop, open an SSH tunnel to the **same port** shown in the URL:

```bash
ssh -L 39945:127.0.0.1:39945 metta@metta1
```

Keep this tunnel open.

### 3) Open the URL and finish login

Open the printed URL in your browser. The SSO flow should redirect to `http://127.0.0.1:<PORT>/oauth/callback`, which
will reach the container through your SSH tunnel. Once completed, the login command in the container will exit.

### 4) Verify

```bash
uv run python devops/mettabox/cli.py exec metta1 -- /usr/local/bin/aws sts get-caller-identity --profile softmax
```

You should see your role ARN and account ID.

## Troubleshooting

### JSONDecodeError in SSO cache

If `aws` complains about a corrupted cache JSON (e.g. `~/.aws/sso/cache/*.json`):

```bash
uv run python devops/mettabox/cli.py exec metta1 -- rm -f /root/.aws/sso/cache/<bad-file>.json
```

Then re-run the login steps.

### `aws sso login` fails with CLI v1

The SSO login command is only available in **AWS CLI v2**. If `aws` resolves to a v1 binary inside a virtualenv,
explicitly use the v2 path:

```bash
/usr/local/bin/aws --version
/usr/local/bin/aws sso login --profile softmax --no-browser
```

If v2 is missing, install it inside the container:

```bash
curl -sSL https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp
/tmp/aws/install -i /usr/local/aws-cli -b /usr/local/bin
```

### Still stuck?

- Check the port in the URL matches your tunnel port.
- Make sure the login command is still running while you open the URL.
- If you restarted the login, use the **latest** URL/port.

## Notes

- Tokens are stored in `/root/.aws/sso/cache/` inside the container.
- Do **not** copy tokens between machines; always use the login flow.
- The mettabox container runs with host networking, so the localhost callback listens on the host network.

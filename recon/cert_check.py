import socket, ssl, json

HOSTS = ["www.dukpion.com.bd", "dukpion.com.bd"]

for host in HOSTS:
    print(f"\n=== {host} ===")
    try:
        # Verification OFF only to read the certificate, no HTTP request is sent.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, 443), timeout=15) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                der = tls.getpeercert(binary_form=True)
        pem = ssl.DER_cert_to_PEM_cert(der)
        open(f"{host}.pem", "w").write(pem)
        print(f"Saved {host}.pem")
    except Exception as e:
        print("Connection failed:", repr(e))
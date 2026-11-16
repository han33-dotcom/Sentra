# Sentra service account handoff

Use the dedicated Sentra Gmail identity for service administration. The primary
custodian handles routine access, and the backup custodian handles recovery.
Confirm access and multifactor authentication together. Keep custodian details,
recovery methods and secure storage locations in the restricted operator inventory.
The dated cutover evidence and remaining acceptance checks are in [SEN-70].

| Service | Administration and contacts | Recovery or access dependency |
| --- | --- | --- |
| Google Cloud and OAuth | The Sentra identity is the sole Owner of the existing project. Use the dedicated mailbox for OAuth user support and as a developer contact alongside the retained team contacts. | Recover the dedicated Google identity first. Check IAM, both existing OAuth clients, redirects and the External / Testing audience. Review project notification contacts separately. |
| Supabase | The Sentra identity is the sole Owner of the existing organization and is the configured billing email recipient. The former Owner remains a Developer to preserve saved queries and reports. | Use the existing organization and project on the Free plan with the spend cap. Keep project recovery and runtime configuration in the restricted operator inventory. |
| Render | Use the Sentra mailbox and the Render password for the existing Free enrollment service. | Recover through the Sentra mailbox. Check the original service, URL, GitHub deployment connection and `main` branch before operating it. |
| Streamlit Community Cloud | Use **Continue with Google** and choose the Sentra identity. The existing viewer is private and uses `ETL-pipeline` / `viewer/app.py`. | Hosting management still depends on the linked `han33-dotcom` GitHub account. Use Google for the Sentra email login. [Signing in with GitHub can update the Streamlit email to match GitHub.][streamlit-sign-in] |

Use an approved personal Google identity for viewer sign-in. The hosting login
and the viewer's own Google sign-in serve different purposes. The WHOOP app owner
continues to manage its developer account.

## Recovery and verification

1. Use the provider's recovery flow and the restricted operator inventory.
   Confirm the intended service, recovery contact and rollback route before
   making access changes. With the backup custodian, verify access to the
   approved recovery locations. Keep recovery codes, hosted settings, enrollment
   encryption and identity-HMAC keys out of GitHub and chat.
2. Sign in fresh and check access to the original project or deployment. Compare
   service URLs, OAuth settings, source control, plans and credential references
   with the private inventory. Preserve the deployed encryption and identity
   keys and the restricted Supabase runtime roles.
3. Check enrollment availability, approved sign-in behavior, private viewer
   sign-in and sign-out, denied access, and the restricted database/Storage
   permissions within the approved verification scope. Record which checks were
   live and which used synthetic data. Keep both collection controls paused as
   described in the [operating guide](operating-guide.md).
4. Record sanitized results in [SEN-70]. The [recovery rehearsal task][SEN-30]
   tracks isolated restore evidence separately.

## Privacy policy and public contact

Notion has been retired. A replacement public Sentra privacy policy URL is
pending. Use [SEN-26] to agree the policy, public contact and publishing location
before giving a new URL to participants or updating a provider dashboard. Verify
the published page from a signed-out browser and check any dashboard or material
that still points to the retired link. Coordinate WHOOP changes with its app owner.

[SEN-26]: https://github.com/han33-dotcom/Sentra/issues/26
[SEN-30]: https://github.com/han33-dotcom/Sentra/issues/30
[SEN-70]: https://github.com/han33-dotcom/Sentra/issues/70
[streamlit-sign-in]: https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-account/sign-in-sign-out

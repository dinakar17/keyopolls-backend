# utils/email_domains.py

"""
Simple email domain utilities for identity verification.
Just update the ALLOWED_ORGANIZATIONAL_DOMAINS list to add/remove allowed domains.
"""

# Organizational email domains that are allowed for verification
ALLOWED_ORGANIZATIONAL_DOMAINS = [
    # Tech companies
    "google.com",
    "microsoft.com",
    "apple.com",
    "bajajauto.co.in",
    "amazon.com",
    "meta.com",
    "facebook.com",
    "netflix.com",
    "uber.com",
    "airbnb.com",
    "spotify.com",
    "twitter.com",
    "linkedin.com",
    "salesforce.com",
    "adobe.com",
    "oracle.com",
    "ibm.com",
    "intel.com",
    "nvidia.com",
    "tesla.com",
    # Indian IT companies
    "tcs.com",
    "infosys.com",
    "wipro.com",
    "hcl.com",
    "techm.com",
    "mindtree.com",
    "accenture.com",
    "cognizant.com",
    "capgemini.com",
    "ltimindtree.com",
    # Indian startups/companies
    "flipkart.com",
    "paytm.com",
    "ola.com",
    "swiggy.com",
    "zomato.com",
    "byju.com",
    "phonepe.com",
    "razorpay.com",
    "freshworks.com",
    "zoho.com",
    # Financial services
    "jpmorgan.com",
    "goldmansachs.com",
    "morganstanley.com",
    "bankofamerica.com",
    "citi.com",
    "wellsfargo.com",
    # Consulting
    "mckinsey.com",
    "bain.com",
    "bcg.com",
    "deloitte.com",
    "pwc.com",
    "ey.com",
    "kpmg.com",
    # Educational institutions
    "stanford.edu",
    "mit.edu",
    "harvard.edu",
    "berkeley.edu",
    "ucla.edu",
    "cmu.edu",
    "iitb.ac.in",
    "iitd.ac.in",
    "iitk.ac.in",
    "iitm.ac.in",
    "iisc.ac.in",
    "nitc.ac.in",
    # Venture Capitalist and Private Equity Firms
    "sequoia.com",
    "a16z.com",
    "ycombinator.com",
]


def is_allowed_organizational_domain(domain: str) -> bool:
    """
    Check if a domain is in the allowed organizational domains list.

    Args:
        domain (str): Email domain to check (e.g., 'google.com')

    Returns:
        bool: True if domain is allowed, False if not allowed
    """
    return domain.lower().strip() in ALLOWED_ORGANIZATIONAL_DOMAINS


def validate_organizational_email(email: str) -> tuple[bool, str]:
    """
    Validate that an email is from an allowed organizational domain.

    Args:
        email (str): Email address to validate

    Returns:
        tuple[bool, str]: (is_valid, error_message_if_invalid)
    """
    if not email or "@" not in email:
        return False, "Invalid email format"

    try:
        domain = email.split("@")[1].lower()
        if not is_allowed_organizational_domain(domain):
            return (
                False,
                f"Email domain '{domain}' is not supported for verification. "
                f"Please contact support to add your organization.",
            )
        return True, ""
    except IndexError:
        return False, "Invalid email format"

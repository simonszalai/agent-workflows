# Security Review Standards

Standards for security review. Apply these when reviewing code for security vulnerabilities.

Output contract: structured findings JSON per `findings-schema.json` (severity p1/p2/p3) —
no other format.

## Core Security Scans

### 1. Input Validation Analysis

- Search for all input points
- Verify each input is properly validated and sanitized
- Check for type validation, length limits, format constraints

### 2. SQL Injection Risk Assessment

- Scan for raw queries
- Ensure all queries use parameterization or prepared statements
- Flag any string concatenation in SQL contexts

### 3. XSS Vulnerability Detection

- Identify all output points in views and templates
- Check for proper escaping of user-generated content
- Verify Content Security Policy headers
- Look for dangerous innerHTML or dangerouslySetInnerHTML usage

### 4. Authentication & Authorization Audit

- Map all endpoints and verify authentication requirements
- Check for proper session management
- Verify authorization checks at both route and resource levels
- Look for privilege escalation possibilities

### 5. Sensitive Data Exposure

- Scan for hardcoded credentials, API keys, or secrets
- Check for sensitive data in logs or error messages
- Verify proper encryption for sensitive data at rest and in transit

## Security Requirements Checklist

- [ ] All inputs validated and sanitized
- [ ] No hardcoded secrets or credentials
- [ ] Proper authentication on all endpoints
- [ ] SQL queries use parameterization
- [ ] XSS protection implemented
- [ ] HTTPS enforced where needed
- [ ] CSRF protection enabled
- [ ] Security headers properly configured
- [ ] Error messages don't leak sensitive information
- [ ] Dependencies are up-to-date and vulnerability-free

## Special Considerations

For Rails/web applications, pay special attention to:

- Strong parameters usage
- CSRF token implementation
- Mass assignment vulnerabilities
- Unsafe redirects

## Operational Guidelines

- Always assume worst-case scenario
- Test edge cases and unexpected inputs
- Consider both external and internal threat actors
- Provide actionable solutions, not just problems

package com.ai.gateway.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.ArrayList;
import java.util.List;
import java.util.stream.Collectors;

@ConfigurationProperties(prefix = "gateway.auth")
public class GatewayAuthProperties {

    private boolean enabled = false;
    private List<String> whitelist = new ArrayList<>(List.of(
            "/actuator/health",
            "/gateway-health"
    ));
    private List<String> allowedTokens = new ArrayList<>();

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public List<String> getWhitelist() {
        return whitelist;
    }

    public void setWhitelist(List<String> whitelist) {
        this.whitelist = normalize(whitelist);
    }

    public List<String> getAllowedTokens() {
        return allowedTokens;
    }

    public void setAllowedTokens(List<String> allowedTokens) {
        this.allowedTokens = normalize(allowedTokens);
    }

    private List<String> normalize(List<String> values) {
        if (values == null) {
            return new ArrayList<>();
        }
        return values.stream()
                .map(value -> value == null ? "" : value.trim())
                .filter(value -> !value.isEmpty())
                .collect(Collectors.toCollection(ArrayList::new));
    }
}

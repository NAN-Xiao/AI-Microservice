package com.example.msgqueue.config;

import org.apache.catalina.connector.Connector;
import org.springframework.boot.web.embedded.tomcat.TomcatServletWebServerFactory;
import org.springframework.boot.web.server.WebServerFactoryCustomizer;
import org.springframework.stereotype.Component;

import java.util.LinkedHashSet;
import java.util.Set;

@Component
public class AdditionalTomcatPortsConfig implements WebServerFactoryCustomizer<TomcatServletWebServerFactory> {

    private final ServerPortsProperties serverPortsProperties;

    public AdditionalTomcatPortsConfig(ServerPortsProperties serverPortsProperties) {
        this.serverPortsProperties = serverPortsProperties;
    }

    @Override
    public void customize(TomcatServletWebServerFactory factory) {
        Set<Integer> ports = new LinkedHashSet<>(serverPortsProperties.getAdditionalPorts());
        ports.remove(factory.getPort());
        if (ports.isEmpty()) {
            return;
        }

        Connector[] connectors = ports.stream()
                .map(this::createHttpConnector)
                .toArray(Connector[]::new);
        factory.addAdditionalTomcatConnectors(connectors);
    }

    private Connector createHttpConnector(int port) {
        Connector connector = new Connector(TomcatServletWebServerFactory.DEFAULT_PROTOCOL);
        connector.setScheme("http");
        connector.setSecure(false);
        connector.setPort(port);
        return connector;
    }
}

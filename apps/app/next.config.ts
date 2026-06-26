import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Permite acessar o dev server por IP na rede local (ex.: celular no mesmo Wi-Fi).
  allowedDevOrigins: ['192.168.15.60'],
  // Fixa a raiz do projeto (evita inferência errada por lockfiles em diretórios pai).
  turbopack: { root: __dirname },
};

export default nextConfig;

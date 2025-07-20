# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.4] - 2025-07-20

### Added

- 💖 **Support Section**: Added cryptocurrency donation addresses for project support
  - USDT (Ethereum Network): Support for project maintenance and development
  - Solana (SOL): Additional donation option for contributors
  - Ripple (XRP): Alternative cryptocurrency support method

### Changed

- 🔗 **Documentation Links**: Updated all relative links to full GitHub URLs for better PyPI compatibility
  - Fixed example file links to use full GitHub URLs
  - Updated contributing and AI usage policy links
  - Enhanced footer navigation with absolute links
- 🔧 **Release Automation**: Improved Makefile release system with comprehensive version management
  - Enhanced version checking across all project files
  - Better release workflow with manual version specification
  - Automated synchronization of version numbers across documentation

### Fixed

- 📚 **README Links**: All documentation links now work properly on PyPI and other platforms
- 🔄 **Version Consistency**: Ensured all files maintain synchronized version numbers during releases

## [0.7.3] - 2025-07-20

### Added

- 🤖 **AI Usage Policy**: Comprehensive transparency documentation
  - Added AI_USAGE.md with detailed policy on AI assistance in development
  - Updated README.md and CONTRIBUTING.md with AI usage references
  - Clear guidelines for contributors using AI tools
  - Transparency about AI-assisted documentation, tests, and examples

## [0.7.2] - 2025-07-15

### Added

- 🚀 **Complete Type Safety**: Comprehensive mypy type annotations across all files
  - Fixed all Django user attribute access (user.id, user.is_staff, user.is_superuser)
  - Added proper type hints for all function parameters and return values
  - Eliminated all mypy errors with strict type checking enabled
  - Enhanced IDE support with better autocompletion and error detection
- 🛡️ **Security Hardening**: Bandit security analysis integration
  - Added .bandit configuration file for security scanning
  - Fixed all high-severity security issues
  - Added security-safe hash operations (usedforsecurity=False)
  - Enhanced Redis Lua script security annotations
- 🔧 **Development Workflow Improvements**: Updated CI/CD and development tools
  - Updated GitHub Actions workflows for Python 3.13 and Django 5.1
  - Enhanced pre-commit hooks with comprehensive type checking
  - Improved Makefile with virtual environment management
  - Added run_with_venv.sh script for consistent environment handling
- 📚 **Code Quality**: Removed mypy ignore overrides for core modules
  - configuration.py and middleware.py now pass strict type checking
  - All example files pass type validation
  - Comprehensive test suite coverage (340+ tests passing)

### Changed

- 🎯 **Type System**: Enhanced Django user compatibility
  - Used getattr() pattern for safe attribute access on AbstractBaseUser/AnonymousUser
  - Maintained backward compatibility while adding type safety
  - Improved error handling for different Django user models
- 🔄 **CI/CD Pipeline**: Modernized development infrastructure
  - Updated to latest Python and Django versions in CI
  - Enhanced security scanning with Bandit integration
  - Improved pre-commit configuration for better developer experience
- 📖 **Documentation**: Enhanced type safety documentation
  - Updated examples with proper type annotations
  - Improved development setup instructions
  - Better IDE integration guidance

### Fixed

- 🐛 **Type Errors**: Resolved all mypy type annotation errors
  - Fixed AbstractBaseUser attribute access in key_functions.py
  - Fixed user attribute access in performance.py, configuration.py, middleware.py
  - Fixed auth_utils.py and utils.py type compatibility issues
- 🔒 **Security Issues**: Addressed all high-severity security warnings
  - Added security-safe cryptographic operations
  - Enhanced Redis Lua script security annotations
  - Improved input validation and sanitization
- 🧪 **Testing**: Enhanced test reliability and coverage
  - All 340+ tests passing with type safety enabled
  - Improved test isolation and consistency
  - Better error reporting and debugging capabilities

### Technical Notes

- This release focuses on production readiness and developer experience
- Type safety improvements enhance IDE support and reduce runtime errors
- Security hardening makes the library more suitable for production deployments
- Recommended upgrade for all users seeking better type safety and security

## [0.5.0] - 2025-07-09

### Added

- 🔥 **Django REST Framework (DRF) Integration**: Comprehensive integration with DRF
  - ViewSet rate limiting with method-specific configurations
  - Serializer-level rate limiting and validation
  - Custom permission classes with rate limiting
  - Advanced examples for ViewSets, Serializers, and Permissions
  - Complete test coverage for all DRF integration patterns
  - Detailed documentation and usage examples in `docs/integrations/drf.md`
  - Production-ready examples in `examples/drf_integration/`
- 📚 Comprehensive DRF documentation and examples
- 🧪 Full test suite for DRF integration (35+ tests)
- 🎯 Advanced DRF patterns: conditional rate limiting, role-based limits, adaptive limits
- 🛠️ DRF-specific utilities and helpers

### Changed

- 🔧 Fixed all decorator usage to use current API (`@rate_limit` instead of `@ratelimit`)
- 📝 Updated all examples to remove deprecated `method=` parameter
- 🧹 Cleaned up codebase and removed unused files
- 📖 Enhanced documentation with DRF integration guide

### Fixed

- 🚫 Removed all deprecated `method=` parameters from decorators
- 🔄 Fixed all import statements to use `rate_limit` instead of `ratelimit`
- 🧪 Fixed test issues with DRF integration examples

## [0.4.2] - 2025-07-08

### Added

- 💬 GitHub Discussions for community support and engagement
- 📚 Enhanced documentation with Discussions integration
- 🏷️ GitHub Discussions badge in README
- 🤝 Updated community support sections across all documentation

### Changed

- 📖 Improved issue and PR templates with Discussions references
- 🎯 Better organization of community support resources

## [0.3.2] - 2025-07-07

### Fixed

- 🔧 **CRITICAL**: Resolved race conditions in database backend increment operations
- ⚡ Implemented atomic F() expressions for database-level counter updates
- 🛡️ Added proper transaction handling to prevent data corruption
- 📊 Enhanced concurrency safety for high-traffic applications

### Changed

- 🔄 Replaced Python-level `+=` operations with database-level `F('count') + 1`
- 🏗️ Improved fixed window and sliding window algorithm consistency
- 📈 Better handling of concurrent requests in database backend

### Technical Notes

- This is a critical security and data integrity fix
- Recommended upgrade for all production deployments
- Addresses community-reported race condition issues

## [0.3.1] - 2025-07-06

### Added

- 💖 Support section with USDT donation address
- 🔧 Enhanced README organization and clarity

### Changed

- 📖 Improved documentation formatting and structure
- 🎨 Better emoji usage in support section

## [0.3.0] - 2025-07-06

### Added

- 🔀 Multi-backend support with automatic fallback
- 🏥 Backend health monitoring and status reporting
- 🏭 Backend factory for dynamic backend instantiation
- 📊 Comprehensive multi-backend test suite (35+ tests)
- 🛠️ Enhanced management command documentation
- 📋 Complete documentation reorganization
- 🔍 Health check and cleanup management commands
- 📈 Production-ready monitoring and alerting support

### Changed

- 📖 Refactored README for better organization
- 🔧 Improved backend selection logic
- 🧪 Enhanced test coverage and quality
- 📋 Updated examples with multi-backend configurations

### Fixed

- 🔗 Fixed all documentation links and references
- 🧹 Cleaned up old documentation and broken links

## [0.2.0] - 2025-07-05

### Added

- 🗄️ In-memory backend implementation with thread safety
- 🧹 Automatic cleanup of expired entries
- 📏 Memory limit configuration with LRU eviction
- 🔄 Backend factory caching for performance
- 🧪 Comprehensive test suite for memory backend
- 📖 Updated documentation and examples

### Changed

- 🏭 Enhanced backend factory with caching support
- 🔧 Improved decorator key generation logic
- 📋 Updated contributing guidelines
- 🗺️ Marked memory backend as completed in roadmap

### Fixed

- 🔧 Fixed Redis integration test cache clearing
- 🐛 Resolved all pre-commit hook issues (black, flake8, isort, mypy)

## [0.1.1] - 2025-07-05

### Fixed

- 🔧 Fixed PyPI badge display issues in README
- 📦 Updated package classifiers for better PyPI compatibility
- 🏷️ Improved Django version badge display
- 📝 Cleaned up CHANGELOG formatting

### Changed

- 📋 Enhanced README badges with better PyPI integration
- 🎨 Added emoji indicators to CHANGELOG for better readability
- 🔄 Updated supported Django versions to include 5.1

## [0.1.0] - 2025-07-05

### Added

- ✨ Rate limiting decorator with configurable keys and rates
- 🔧 Rate limiting middleware with path-based configuration
- 🔌 Redis backend with sliding window and fixed window algorithms
- 🧪 Comprehensive test suite with >90% coverage
- 📖 Documentation with architecture design and usage examples
- 🚀 CI/CD pipeline with GitHub Actions
- 🔒 Pre-commit hooks for code quality
- 🐍 Support for Python 3.9, 3.10, 3.11, and 3.12
- 🌐 Support for Django 3.2, 4.0, 4.1, 4.2, and 5.0
- 📄 MIT License

### Features

- ⚡ Atomic rate limiting operations using Redis Lua scripts
- 🛣️ Configurable rate limits per path in middleware
- 🔑 Custom key functions for advanced use cases
- 📊 Standard rate limiting headers (X-RateLimit-\*)
- 🚫 Blocking and non-blocking rate limiting modes
- 🏥 Health check functionality for Redis backend
- 🛡️ Comprehensive error handling and logging

### Documentation

- 📚 Complete README with usage examples
- 🏗️ Architecture design document
- 📋 API reference documentation
- 🤝 Contributing guidelines
- 📝 Issue and PR templates

[Unreleased]: https://github.com/YasserShkeir/django-smart-ratelimit/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/YasserShkeir/django-smart-ratelimit/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/YasserShkeir/django-smart-ratelimit/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/YasserShkeir/django-smart-ratelimit/releases/tag/v0.1.0

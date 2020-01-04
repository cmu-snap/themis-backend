'use strict';
module.exports = (sequelize, DataTypes) => {
  const Flow = sequelize.define('Flow', {
    btlbw: {
      type: DataTypes.INTEGER,
      allowNull: false,
    },
    rtt: {
      type: DataTypes.INTEGER,
      allowNull: false,
    },
    queueSize: {
      type: DataTypes.INTEGER,
      allowNull: false,
    },
    cca: {
      type: DataTypes.ENUM('BBR', 'Cubic', 'Reno'),
      allowNull: false,
    },
    test: {
      type: DataTypes.ENUM('iperf-website', 'iperf16-website', 'apache-website', 'video'),
      allowNull: false
    },
    name: DataTypes.STRING,
    status: {
      type: DataTypes.ENUM(
        'Queued for download',
        'Downloading',
        'Queued for metrics',
        'Processing metrics',
        'Completed',
        'Failed download',
        'Failed to get metrics'
      ),
      allowNull: false,
      defaultValue: 'Queued for download'
    }
  }, {});

  Flow.associate = (models) => {
    Flow.belongsTo(models.Experiment, {
      foreignKey: 'experimentId',
      onDelete: 'CASCADE',
    });
  };

  return Flow;
};
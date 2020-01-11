'use strict';
const params = require('../parameters.js');

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
      type: DataTypes.ENUM(params.ccas),
      allowNull: false,
    },
    test: {
      type: DataTypes.ENUM(Object.keys(params.tests)),
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
    },
    isFinished: {
      type: DataTypes.BOOLEAN,
      allowNull: false,
      defaultValue: false
    },
    metrics: {
      type: DataTypes.JSON,
      allowNull: true
    }
  }, {
    setterMethods: {
      status(value) {
        const finishedStatus = ['Completed', 'Failed download', 'Failed to get metrics'];
        this.setDataValue('isFinished', finishedStatus.includes(value));
        this.setDataValue('status', value);
      },
    }
  });

  Flow.associate = (models) => {
    Flow.belongsTo(models.Experiment, {
      foreignKey: 'experimentId',
      onDelete: 'CASCADE',
    });
  };

  return Flow;
};
